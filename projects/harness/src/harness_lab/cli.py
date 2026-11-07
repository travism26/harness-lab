"""The `harness` command: one-shot. Prints the final answer; exits non-zero on failure."""

import argparse
import os
import sys

from harness_lab.client import DEFAULT_ENDPOINT, ModelClient, ModelError
from harness_lab.loop import ConfigError, resolve_max_turns, run

ENDPOINT_VAR = "HARNESS_ENDPOINT"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="harness", description="Ask the model a question.")
    parser.add_argument("question")
    parser.add_argument("--max-turns", type=int, help="turn cap (default 10, or HARNESS_MAX_TURNS)")
    parser.add_argument("--endpoint", help=f"Messages endpoint (default {DEFAULT_ENDPOINT}, or {ENDPOINT_VAR})")
    args = parser.parse_args(argv)
    try:
        client = ModelClient(endpoint=args.endpoint or os.environ.get(ENDPOINT_VAR) or DEFAULT_ENDPOINT)
        result = run(args.question, client, max_turns=resolve_max_turns(args.max_turns))
    except (ModelError, ConfigError) as err:
        print(f"harness: {err}", file=sys.stderr)
        return 1
    if result.ok:
        print(result.answer)
        return 0
    print(f"harness: {result.stop_reason.replace('_', ' ')}: {result.error}", file=sys.stderr)
    print(f"harness: run log: {result.log_path}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
