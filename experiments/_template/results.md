# Experiment results

| Field | Value |
|---|---|
| Request | `{{request}}` |
| Commit | `{{commit}}` |
| Uncommitted changes | {{uncommitted}} |
| Started (UTC) | {{started-utc}} |
| Cost cap (USD) | {{cost-cap}} |
| Timebox (minutes) | {{timebox}} |
| Model / login | {{login}} |
| Agent cost (USD) |  |
| Cost basis | client-estimate |
| Claude Code version |  |

## Checks

| # | Check | Exit code | Result | Duration (s) |
|---|---|---|---|---|
| 1 | {{check-name}} | {{exit-code}} | {{result}} | {{duration}} |

Result: {{passed}} pass, {{failed}} fail, {{not-run}} not run.

## Commands

### 1. {{check-name}}

```sh
{{check-command}}
```

Pass means: {{pass-means}}
