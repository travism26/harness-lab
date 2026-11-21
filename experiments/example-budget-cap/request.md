# Experiment request: `--max-budget-usd` stops a print-mode run at its cap

This request is an example of the format. It is committed and has not been run.

## Hypothesis

A Claude Code print-mode run started with `--max-budget-usd 0.10` stops once its estimated spend reaches $0.10. It ends with the result subtype `error_max_budget_usd` and a non-zero exit code. Its `total_cost_usd` is at least $0.10 and at most $0.35, because the docs say spend can pass the cap.

## Public sources

- https://code.claude.com/docs/en/cli-reference (the `--max-budget-usd` row: print mode only, checked against a client-side estimate, spend can pass the cap)
- https://code.claude.com/docs/en/headless (`--output-format json` and its `total_cost_usd` field; a failed run exits non-zero)
- https://code.claude.com/docs/en/agent-sdk/cost-tracking (the `error_max_budget_usd` result subtype)

## Checks

Every check reads `evidence.json` in this folder. `Model / login` below says how that file is made.

### 1. The run ended at its budget cap

```sh
python3 -c "import json; r = json.load(open('evidence.json')); assert r['subtype'] == 'error_max_budget_usd', r"
```

Pass means: the result's `subtype` is `error_max_budget_usd`.

### 2. The run exited non-zero

```sh
python3 -c "import json; r = json.load(open('evidence.json')); assert r['exit_code'] != 0, r"
```

Pass means: the `claude` process reported the capped run as a failure.

### 3. Estimated spend reached the cap

```sh
python3 -c "import json; r = json.load(open('evidence.json')); assert r['total_cost_usd'] >= 0.10, r"
```

Pass means: `total_cost_usd` is at least the $0.10 cap, so the run did not stop early for another reason.

### 4. Estimated spend stayed near the cap

```sh
python3 -c "import json; r = json.load(open('evidence.json')); assert r['total_cost_usd'] <= 0.35, r"
```

Pass means: `total_cost_usd` is no more than $0.25 above the cap.

## Cost cap (USD)

0.50

## Timebox (minutes)

20

## Model / login

subscription

This Experiment needs one live model call, made outside the checks because a check has no login: `claude -p --max-budget-usd 0.10 --output-format json` with a prompt that needs many turns. Save the process's exit code and the result's `subtype` and `total_cost_usd` to `experiments/example-budget-cap/evidence.json` as `exit_code`, `subtype` and `total_cost_usd`, with no text from the model. The call's spend counts against this request's cost cap. The cap is checked against the CLI's own estimate on either login, so the subscription login is enough.

## Revert

Close the draft PR and delete the `experiment/example-budget-cap` branch.
