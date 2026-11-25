"""Validate an Experiment request and run its checks.

Usage:
    uv run python experiments/experiment.py validate <request.md>
    uv run python experiments/experiment.py run <request.md> [--check-timeout SECONDS] [--elapsed-minutes N] [--out PATH]

The protocol is in experiments/README.md. This module uses the standard library only.
"""

from __future__ import annotations

import argparse
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from ipaddress import ip_address
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_README = Path(__file__).resolve().parent / "README.md"
DEFAULT_CHECK_TIMEOUT_S = 300
MAX_CHECKS = 5
README_LABEL = "experiments/README.md"

REQUIRED_HEADINGS = (
    "Hypothesis",
    "Public sources",
    "Checks",
    "Cost cap (USD)",
    "Timebox (minutes)",
    "Model / login",
    "Revert",
)
LOGINS = ("subscription", "metered key")

PLACEHOLDER_RE = re.compile(r"\{\{[a-z][a-z0-9-]*\}\}")
# Same family as the token pattern in factory/record.py; a separate copy, built from
# pieces so this file does not match it.
TOKEN_RE = re.compile(
    "|".join(
        [
            r"sk-(?:ant|or)-",
            r"\bsk-[A-Za-z0-9_-]{6,}",
            r"gh[pousr]_[A-Za-z0-9]{10,}",
            "github" + "_pat_",
            r"xox[abposr]-",
            r"eyJ[A-Za-z0-9_-]{10,}",
            r"AKIA[0-9A-Z]{16}",
            "-----BEGIN [A-Z ]*PRIVATE " + "KEY-----",
        ]
    )
)
COST_RE = re.compile(r"^\$?\d+(\.\d{1,2})?$")
INT_RE = re.compile(r"^\d+$")
SOURCE_RE = re.compile(r"^- (\S+)(?:\s.*)?$")
CHECK_HEADING_RE = re.compile(r"###(?!#)\s*(.*)$")

_CEILING_COST_RE = re.compile(r"^\|\s*Cost cap \(USD\)\s*\|\s*(\d+(?:\.\d+)?)\s*\|\s*$")
_CEILING_TIMEBOX_RE = re.compile(r"^\|\s*Timebox \(minutes\)\s*\|\s*(\d+)\s*\|\s*$")


# --- data ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Check:
    name: str
    command: str
    pass_means: str


@dataclass(frozen=True)
class Request:
    path: Path
    checks: tuple[Check, ...]
    cost_cap_usd: Decimal
    timebox_minutes: int
    login: str
    cost_cap_text: str = ""


@dataclass(frozen=True)
class Ceilings:
    cost_cap_usd: Decimal
    timebox_minutes: int


@dataclass
class CheckResult:
    check: Check
    exit_code: int | None
    timed_out: bool
    result: str  # "pass" | "fail" | "not run"
    duration_s: float | None


class CeilingError(Exception):
    pass


# --- ceilings -----------------------------------------------------------------------


def read_ceilings(readme_path: Path = DEFAULT_README) -> Ceilings:
    try:
        lines = Path(readme_path).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as exc:
        raise CeilingError(f"unreadable: {exc}") from exc
    costs = [m.group(1) for line in lines if (m := _CEILING_COST_RE.match(line))]
    boxes = [m.group(1) for line in lines if (m := _CEILING_TIMEBOX_RE.match(line))]
    if len(costs) != 1 or len(boxes) != 1:
        raise CeilingError("each ceiling row must appear exactly once")
    cost, box = Decimal(costs[0]), int(boxes[0])
    if cost <= 0 or box <= 0:
        raise CeilingError("ceilings must be above zero")
    return Ceilings(cost, box)


# --- credential deny-list -----------------------------------------------------------

_CRED_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "dumps the environment (env or printenv)",
        re.compile(r"(?<![\w.-])(?:[\w./]*/)?(?:env|printenv)(?![\w.-])"),
    ),
    (
        "reads the environment from a program (environ, getenv or process.env)",
        re.compile(
            r"(?<![A-Za-z0-9_])(?:environ|getenv)(?![A-Za-z0-9_])|(?<![\w.])process\.env(?![\w])"
        ),
    ),
    (
        "dumps the environment with a bare set",
        re.compile(r"(?:^|[;&|({\n`]|\$\()\s*set\s*(?:$|[;&|)>}`\n])"),
    ),
    (
        "dumps variables with export -p, declare -p or typeset -p",
        re.compile(r"(?<![\w.-])(?:export|declare|typeset)\s+-p(?![\w-])"),
    ),
    ("reads a .env file", re.compile(r"(?<![\w])\.env(?:rc)?(?![\w])")),
    (
        "reads a credential store",
        re.compile(
            r"(?<!\w)\.claude(?!\w)|(?<!\w)\.config/gh(?![\w-])|(?<!\w)\.(?:ssh|aws|netrc)(?!\w)"
            r"|(?<!\w)\.git-credentials(?![\w-])"
            r"|(?<![\w.-])security\s+(?:find-|dump-|export)"
        ),
    ),
    (
        "uses gh auth or git credential",
        re.compile(r"(?<![\w.-])gh\s+auth(?![\w-])|(?<![\w.-])git\s+credential"),
    ),
)
_VAR_RE = re.compile(r"\$\{?[!#]?([A-Za-z_][A-Za-z0-9_]*)")
_SECRET_NAME_RE = re.compile(r"key|token|secret", re.IGNORECASE)


def credential_reasons(command: str) -> list[str]:
    reasons = [reason for reason, pattern in _CRED_RULES if pattern.search(command)]
    for m in _VAR_RE.finditer(command):
        if _SECRET_NAME_RE.search(m.group(1)):
            reasons.append(f"references the variable ${m.group(1)} (name holds KEY, TOKEN or SECRET)")
    return reasons


# --- parsing ------------------------------------------------------------------------


def _is_fence(line: str) -> bool:
    return line.strip().startswith("```")


def _split_sections(text: str) -> list[tuple[str, list[str]]]:
    sections: list[tuple[str, list[str]]] = []
    in_fence = False
    for line in text.splitlines():
        if _is_fence(line):
            in_fence = not in_fence
        elif not in_fence and line.startswith("## "):
            sections.append((line[3:].strip(), []))
            continue
        if sections:
            sections[-1][1].append(line)
    return sections


def _nonblank(lines: list[str]) -> list[str]:
    return [line.strip() for line in lines if line.strip()]


def _check_source(line: str) -> str | None:
    m = SOURCE_RE.match(line)
    if not m:
        return "is not a list item of the form '- https://host/path'"
    url = m.group(1)
    try:
        parts = urlsplit(url)
        host = parts.hostname or ""
    except ValueError:
        return "is not a valid URL"
    if parts.scheme != "https":
        return "must start with https://"
    if "@" in parts.netloc:
        return "must not contain userinfo"
    if "." not in host or host == "localhost":
        return "must have a public host name"
    try:
        ip_address(host.strip("[]"))
    except ValueError:
        return None
    return "must not be an IP address"


def _finish_check(name: str, blocks: list[str], prose: list[str], errors: list[str], out: list[Check]) -> None:
    label = f"check {name!r}"
    ok = True
    if not name:
        errors.append("a check has an empty name")
        ok = False
    if len(blocks) != 1:
        errors.append(f"{label} must have exactly one code block, found {len(blocks)}")
        ok = False
    elif not blocks[0]:
        errors.append(f"{label} has an empty command")
        ok = False
    pass_means = ""
    for i, line in enumerate(prose):
        if line.strip().startswith("Pass means:"):
            parts = [line.strip()[len("Pass means:") :].strip()]
            for nxt in prose[i + 1 :]:
                if not nxt.strip():
                    break
                parts.append(nxt.strip())
            pass_means = " ".join(p for p in parts if p).strip()
            break
    if not pass_means:
        errors.append(f"{label} needs a 'Pass means:' line with text")
        ok = False
    if ok:
        out.append(Check(name, blocks[0], pass_means))


def _parse_checks(lines: list[str], errors: list[str]) -> tuple[list[Check], int]:
    """The well-formed checks, and how many '### ' check headings the section has."""
    checks: list[Check] = []
    count = 0
    in_fence = False
    buf: list[str] = []
    cur: tuple[str, list[str], list[str]] | None = None  # name, blocks, prose
    for line in lines:
        if _is_fence(line):
            if not in_fence:
                in_fence, buf = True, []
            else:
                in_fence = False
                if cur:
                    cur[1].append("\n".join(buf).strip())
            continue
        if in_fence:
            buf.append(line)
            continue
        m = CHECK_HEADING_RE.match(line)
        if m:
            if cur:
                _finish_check(cur[0], cur[1], cur[2], errors, checks)
            cur = (m.group(1).strip(), [], [])
            count += 1
        elif cur:
            cur[2].append(line)
    if in_fence:
        errors.append("Checks has an unclosed code block")
    if cur:
        _finish_check(cur[0], cur[1], cur[2], errors, checks)
    return checks, count


def validate_text(
    text: str, path: Path, readme_path: Path = DEFAULT_README
) -> tuple[Request | None, list[str]]:
    # Reported alone: every other message quotes the file, and none may echo the string.
    if TOKEN_RE.search(text):
        return None, ["the file holds a token-shaped string (not shown); remove it first"]
    errors: list[str] = []
    for placeholder in sorted(set(PLACEHOLDER_RE.findall(text))):
        errors.append(f"unfilled template placeholder {placeholder}")

    sections = _split_sections(text)
    bodies: dict[str, list[str]] = {}
    for heading, section_body in sections:
        if heading not in REQUIRED_HEADINGS:
            errors.append(f"unknown heading '## {heading}'")
        elif heading in bodies:
            errors.append(f"heading '## {heading}' appears more than once")
        else:
            bodies[heading] = section_body
    for heading in REQUIRED_HEADINGS:
        if heading not in bodies:
            errors.append(f"missing required heading '## {heading}'")
        elif not _nonblank(bodies[heading]):
            errors.append(f"section '## {heading}' is empty")

    def body(heading: str) -> list[str]:
        return _nonblank(bodies.get(heading, []))

    for line in body("Public sources"):
        problem = _check_source(line)
        if problem:
            errors.append(f"public source '{line}' {problem}")

    checks: list[Check] = []
    if "Checks" in bodies and body("Checks"):
        checks, count = _parse_checks(bodies["Checks"], errors)
        if count == 0:
            errors.append("Checks has no '### ' check; need 1 to 5")
        elif count > MAX_CHECKS:
            errors.append(f"Checks has {count} checks; at most {MAX_CHECKS} are allowed")
        for check in checks:
            for reason in credential_reasons(check.command):
                errors.append(f"check {check.name!r}: command {reason}")

    try:
        ceilings: Ceilings | None = read_ceilings(readme_path)
    except CeilingError:
        ceilings = None
        errors.append(f"cannot read the ceilings from {README_LABEL}; every request is invalid")

    cost = Decimal(0)
    cost_text = ""
    lines = body("Cost cap (USD)")
    if lines:
        if len(lines) == 1 and COST_RE.match(lines[0]):
            cost_text = lines[0].lstrip("$")
            try:
                cost = Decimal(cost_text)
            except InvalidOperation:
                cost = Decimal(0)
            if cost <= 0:
                errors.append("Cost cap (USD) must be above zero")
            elif ceilings and cost > ceilings.cost_cap_usd:
                errors.append(
                    f"Cost cap (USD) {cost_text} is above the ceiling {ceilings.cost_cap_usd} in {README_LABEL}"
                )
        else:
            errors.append("Cost cap (USD) must be one number such as 0.50")

    box = 0
    lines = body("Timebox (minutes)")
    if lines:
        if len(lines) == 1 and INT_RE.match(lines[0]):
            box = int(lines[0])
            if box <= 0:
                errors.append("Timebox (minutes) must be above zero")
            elif ceilings and box > ceilings.timebox_minutes:
                errors.append(
                    f"Timebox (minutes) {box} is above the ceiling {ceilings.timebox_minutes} in {README_LABEL}"
                )
        else:
            errors.append("Timebox (minutes) must be one whole number")

    login = ""
    lines = body("Model / login")
    if lines:
        login = lines[0]
        if login not in LOGINS:
            errors.append("Model / login must start with 'subscription' or 'metered key'")

    if errors:
        return None, errors
    return Request(Path(path), tuple(checks), cost, box, login, cost_text), []


def validate_file(
    path: Path, readme_path: Path = DEFAULT_README
) -> tuple[Request | None, list[str]]:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return None, [f"cannot read {path}: {exc}"]
    return validate_text(text, Path(path), readme_path)


# --- runner -------------------------------------------------------------------------


def scrubbed_env(home: str) -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": home,
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }


def _tail(data: bytes | None) -> str:
    return (data or b"").decode("utf-8", errors="replace")[-2000:]


def _kill_group(pgid: int) -> None:
    try:
        os.killpg(pgid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def run_checks(
    checks,
    cwd: Path,
    timebox_s: float,
    check_timeout_s: float = DEFAULT_CHECK_TIMEOUT_S,
    clock=time.monotonic,
    log=sys.stderr,
) -> list[CheckResult]:
    deadline = clock() + timebox_s
    results: list[CheckResult] = []
    with tempfile.TemporaryDirectory() as home:
        for check in checks:
            if clock() >= deadline:
                results.append(CheckResult(check, None, False, "not run", None))
                print(f"--- {check.name}: not run", file=log)
                continue
            start = clock()
            proc = subprocess.Popen(
                ["/bin/sh", "-c", check.command],
                cwd=cwd,
                env=scrubbed_env(home),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
            timed_out = False
            try:
                out, _ = proc.communicate(timeout=max(0.0, min(check_timeout_s, deadline - clock())))
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_group(proc.pid)
                try:
                    out, _ = proc.communicate(timeout=5)
                except subprocess.TimeoutExpired:  # a process outside the group holds the pipe
                    out = b""
            _kill_group(proc.pid)  # whatever the check left running in the background
            duration = clock() - start
            if timed_out:
                code, result = None, "fail"
            else:
                code = proc.returncode
                result = "pass" if code == 0 else "fail"
            results.append(CheckResult(check, code, timed_out, result, duration))
            print(f"--- {check.name}: {result}", file=log)
            tail = _tail(out)
            if tail:
                print(tail, file=log)
    return results


def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def git_facts(cwd: Path) -> tuple[str, str]:
    head = _git(["rev-parse", "HEAD"], cwd)
    sha = head.stdout.strip() if head and head.returncode == 0 else ""
    commit = sha if re.fullmatch(r"[0-9a-f]{40}", sha) else "unknown"
    status = _git(["status", "--porcelain"], cwd)
    if status is None or status.returncode != 0:
        return commit, "unknown"
    return commit, "yes" if status.stdout.strip() else "no"


def _request_label(path: Path) -> str:
    top = _git(["rev-parse", "--show-toplevel"], Path(path).resolve().parent)
    if top and top.returncode == 0 and top.stdout.strip():
        try:
            return Path(path).resolve().relative_to(Path(top.stdout.strip()).resolve()).as_posix()
        except ValueError:
            pass
    return str(path)


# --- results ------------------------------------------------------------------------


def _display_name(name: str) -> str:
    return re.sub(r"^\d+\.\s+", "", name)


def render_results(
    request: Request,
    results: list[CheckResult],
    commit: str,
    uncommitted: str,
    started_utc: str,
    request_label: str,
) -> str:
    counts = {k: sum(1 for r in results if r.result == k) for k in ("pass", "fail", "not run")}
    out = [
        "# Experiment results",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Request | `{request_label}` |",
        f"| Commit | `{commit}` |",
        f"| Uncommitted changes | {uncommitted} |",
        f"| Started (UTC) | {started_utc} |",
        f"| Cost cap (USD) | {request.cost_cap_text} |",
        f"| Timebox (minutes) | {request.timebox_minutes} |",
        f"| Model / login | {request.login} |",
        "| Agent cost (USD) |  |",
        "| Cost basis | client-estimate |",
        "| Claude Code version |  |",
        "",
        "## Checks",
        "",
        "| # | Check | Exit code | Result | Duration (s) |",
        "|---|---|---|---|---|",
    ]
    for i, r in enumerate(results, 1):
        name = _display_name(r.check.name).replace("|", "\\|")
        code = "timeout" if r.timed_out else ("" if r.exit_code is None else str(r.exit_code))
        dur = "" if r.duration_s is None else f"{r.duration_s:.2f}"
        out.append(f"| {i} | {name} | {code} | {r.result} | {dur} |")
    out += [
        "",
        f"Result: {counts['pass']} pass, {counts['fail']} fail, {counts['not run']} not run.",
        "",
        "## Commands",
    ]
    for i, r in enumerate(results, 1):
        out += [
            "",
            f"### {i}. {_display_name(r.check.name)}",
            "",
            "```sh",
            r.check.command,
            "```",
            "",
            f"Pass means: {r.check.pass_means}",
        ]
    return "\n".join(out) + "\n"


# --- CLI ----------------------------------------------------------------------------


def _positive_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value}") from None
    if not number > 0:
        raise argparse.ArgumentTypeError("must be above zero")
    return number


def _nonneg_float(value: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {value}") from None
    if not number >= 0:
        raise argparse.ArgumentTypeError("must be zero or more")
    return number


def _report_invalid(path: Path, errors: list[str]) -> None:
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    noun = "error" if len(errors) == 1 else "errors"
    print(f"invalid: {path} ({len(errors)} {noun})", file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="experiment.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p_val = sub.add_parser("validate", help="check a request file")
    p_val.add_argument("request", type=Path)
    p_run = sub.add_parser("run", help="validate a request, then run its checks")
    p_run.add_argument("request", type=Path)
    p_run.add_argument("--check-timeout", type=_positive_float, default=DEFAULT_CHECK_TIMEOUT_S)
    p_run.add_argument("--elapsed-minutes", type=_nonneg_float, default=0.0)
    p_run.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    request, errors = validate_file(args.request)
    if request is None:
        _report_invalid(args.request, errors)
        return 1 if args.command == "validate" else 2
    if args.command == "validate":
        print(f"ok: {args.request}")
        return 0

    folder = args.request.resolve().parent
    out_path = args.out or folder / "results.md"
    timebox_s = max(0.0, (request.timebox_minutes - args.elapsed_minutes) * 60)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    commit, uncommitted = git_facts(folder)  # before the checks, which may write files
    results = run_checks(request.checks, folder, timebox_s, args.check_timeout)
    text = render_results(request, results, commit, uncommitted, started, _request_label(args.request))
    out_path.write_text(text, encoding="utf-8")
    passed = sum(1 for r in results if r.result == "pass")
    print(f"{passed} of {len(results)} checks passed")
    print(f"results: {out_path}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
