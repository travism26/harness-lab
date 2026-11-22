# ts-sandbox

The Lab's Node.js/TypeScript Sandbox: a small service and a check that reports each Stage as JSON. Lab-wide terms are in the [root glossary](../../GLOSSARY.md).

## Language

**Sandbox**:
This Project: a small known-good service whose check is the thing being exercised, not a product.
_Avoid_: Demo, template, example app

**Stage**:
One named step of the check (`install`, `typecheck`, `lint` or `test`) that runs one command.
_Avoid_: Step, job, phase

**Stage status**:
How a Stage ended: `pass`, `fail`, or `not-run` when a failed `install` kept it from starting.
_Avoid_: Result, outcome, skipped

**Summary**:
The one JSON object `./check --json` prints: every Stage with its Stage status, duration and command, plus `passed` and `total`.
_Avoid_: Report, Run record, result file

**Pass rate**:
`passed` out of `total` in a Summary: the Stages with status `pass` over all Stages, `not-run` included.
_Avoid_: Score, coverage, success rate

**Tally**:
The `passed` and `total` counts for a list of Stage statuses; what the service's domain module computes and `POST /tally` returns.
_Avoid_: Summary, count, score

**Planted defect**:
One deliberate fault put into a temp copy of the Sandbox to show that exactly one Stage fails on it. It is never committed.
_Avoid_: Bug, mutation, broken fixture
