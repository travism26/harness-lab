# spring-sandbox

A known-good Spring Boot service whose check reports, Stage by Stage, whether verification passed, in a format the other stacks' sandboxes share. Lab-wide terms (Project, Bench and the rest) are in the [root glossary](../../GLOSSARY.md).

## Language

**Sandbox**:
This Project: a small service kept correct on purpose, so a failed Stage comes from the change under test and not from the fixture.
_Avoid_: Demo, template, starter

**Stage**:
One named step of the check, run as one command: `compile`, `checkstyle`, `test` or `archunit`, in that order.
_Avoid_: Step, phase, job

**Stage status**:
How a Stage ended: `pass`, `fail`, or `not-run` when it needs the output of a Stage that did not pass.
_Avoid_: Result, outcome, skipped

**Summary**:
The one JSON object `./check --json` prints: the Project, the stack, every Stage with its Stage status, duration and command, and the Pass rate.
_Avoid_: Report, results file

**Pass rate**:
The Stages that passed out of all Stages, written `passed`/`total`. A `not-run` Stage counts in the total only. The service's one domain class holds the same pair of numbers.
_Avoid_: Score, success rate, coverage

**Planted defect**:
One deliberate fault put into a temporary copy of the Sandbox to show that exactly one Stage fails on it. It is never committed.
_Avoid_: Bug, mutation, broken fixture
