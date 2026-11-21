---
name: verify-ts
description: Run the ts-sandbox check and report each stage's status and the pass rate. Use when asked to verify ts-sandbox, run its check, or report its pass rate.
allowed-tools: Bash(./check --json)
---

# verify-ts

Run the ts-sandbox check once and report what it printed. The report is the whole job: this skill observes the Project and changes nothing in it.

## Steps

1. From `projects/ts-sandbox/` (the folder that holds this Project's `check`), run exactly this, once:

   ```bash
   ./check --json
   ```

   Stdout is one JSON object, the Summary. Stage output goes to stderr. A non-zero exit code is a result to report.

2. Report from that run only:
   - one table row per entry in `stages`, in the order printed: `name`, `status`, `duration_ms`, `command`;
   - the pass rate as `passed/total` (for example `3/4`) and the exit code;
   - for each stage with status `fail`, the first error lines of its stderr output, quoted as printed.

   If stdout is anything other than one JSON object with `stages`, `passed` and `total`, say so, quote what was printed, and give no pass rate.

3. Stop. The turn ends with the report, whether the pass rate is 4/4 or 0/4.

## Boundaries

- **Leave every file as it is.** Report a failing stage; fixing it is a separate request. Edit, create and delete nothing. The check's own `npm ci` writing `node_modules/` is the one exception, and it is the check's doing.
- **Read only the check's output.** Leave secrets, credentials, tokens and `.env` files unopened, and leave the environment unprinted (no `env`, no `printenv`).
- **Run only that one command.** Make no model call, API request or web request, start no subagent, and contact no service. The only network use is the check's `npm ci` fetching the packages locked in `package-lock.json`.
