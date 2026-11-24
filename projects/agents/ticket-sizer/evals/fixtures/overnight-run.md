# Run the three open sandbox Goals overnight on the laptop, with no one at the keyboard

## What

Start one Claude Code session before bed that works through the three open sandbox Goals (Spring, Go, Node.js/TypeScript) in order, without asking me anything. Where a step needs a decision, the session picks the safest option, writes the choice and the reason as one line in `decisions.tsv`, and carries on.

## Rules for the run

- No pushes to `main`, no merges, no label changes.
- Each Goal ends on a draft pull request.
- If a project check fails twice, the session stops that Goal, records it in `decisions.tsv` and moves to the next.
- A hard cost cap for the whole night.

## Done looks like

In the morning I open `decisions.tsv`, read every decision the session made without me, and audit each one before I touch any of the draft pull requests.
