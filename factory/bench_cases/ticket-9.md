# Episode 1, ticket 3: the loop, the run log and the harness command

Part of #6. Depends on tickets 1 (https://github.com/travism26/harness-lab/issues/7) and 2 (https://github.com/travism26/harness-lab/issues/8) being merged.

- `uv run harness "question"` (from the repo root or `projects/harness/`; the entry point is declared in the harness's own pyproject): one-shot; prints the final answer and exits non-zero on missing key, provider error or turn cap.
- The loop: send the question, run any `read_file` tool call, return the tool result, repeat until a final answer. Turn cap is a setting, default 10.
- Run log: one JSON-lines file per Run in a gitignored `projects/harness/runs/` folder. Events: each request, reply, tool call, tool result, token usage, cost only when OpenRouter reports it (never estimated), and the stop reason (final answer, turn cap, provider error, refused tool call).

Acceptance: through the one seam in #6 (the real command pointed at the stand-in model): a one-Turn answer, a tool call Run, a refused path, turn cap, provider error, and Run log contents including the stop reason.

Grill answers behind this: one-shot command (Q2), run log (Q3, Q11), turn cap and stop reasons (Q5), runs/ gitignored (Q10).


> **Paths updated 2026-11-07 after #20 (lab layout):** the harness now lives in `projects/harness/`. New ADRs are numbered from the highest in the lab (next: 0009).

