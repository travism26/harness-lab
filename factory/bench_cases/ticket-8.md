# Episode 1, ticket 2: read_file tool confined to the workspace

Part of #6. Depends on ticket 1 (https://github.com/travism26/harness-lab/issues/7) being merged.

- `read_file` reads a file inside the `projects/harness/workspace/` folder only. Any path that resolves outside it (including `..` and symlink escapes) is refused with a tool result saying so.
- Commit `projects/harness/workspace/` with one sample file so the demo works after cloning.
- Tool definition in Anthropic's tool format so the model can call it.

Acceptance: tests show a successful read, a missing file, a `..` escape refused and a symlink escape refused.

Grill answers behind this: one tool, read_file in a workspace folder (Q1); committed sample file (Q10).


> **Paths updated 2026-11-07 after #20 (lab layout):** the harness now lives in `projects/harness/`. New ADRs are numbered from the highest in the lab (next: 0009).

