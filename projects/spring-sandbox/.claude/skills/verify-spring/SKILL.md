---
name: verify-spring
description: Run the spring-sandbox check once and report each stage's status and the pass rate. Use when asked to verify, check or score projects/spring-sandbox.
---

Verify `projects/spring-sandbox` by running its check once and reporting what it printed. The check is the only command this skill runs.

1. From `projects/spring-sandbox/`, the folder that holds `check`, run exactly:

   ```bash
   ./check --json
   ```

   Stdout is one JSON object: `project`, `stack`, a `stages` list (each entry has `name`, `status`, `duration_ms` and `command`), `passed` and `total`. Build output goes to stderr. A non-zero exit code means at least one stage did not pass. That is a result to report, not an error to work around.

2. Report these four things and nothing else:
   - a table with one row per stage, in the order printed: name, status, duration in ms. A status is `pass`, `fail` or `not-run`; `not-run` means the stage needs compiled classes and `compile` did not pass;
   - `Pass rate: <passed>/<total>`, with both numbers copied from the JSON;
   - the exit code;
   - for each `fail` stage, the first error lines that stage wrote to stderr, quoted.

   If stdout is not one JSON object (for example, no JDK is installed), report the exit code and the last lines of stderr, and give no pass rate.

3. Stop. One run of the check is the whole job, even when a stage fails.

Limits:

- Edit nothing. Don't create, change or delete any file, and don't fix a failing stage. Say what failed and leave the fix to whoever asked.
- Read no secrets: no `.env` or other environment files, no credentials or tokens, no `env` or `printenv`.
- Call no model, API or other service. The only network use is the check's own download of its locked dependencies.
