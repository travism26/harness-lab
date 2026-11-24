---
name: workflow
description: Copy a Lab scenario's steps into the session todo list. Use when the user types /workflow <scenario> (small, medium, big, huge, poc, bug, unattended).
---

# /workflow <scenario>

Copy one Lab scenario's steps into the session's todo list, so the work follows the flow in `docs/skill-workflows.md`. Use whichever todo or task tool this Claude Code version gives you (TodoWrite or the task tools).

This skill is descriptive only. It does not apply GitHub labels, open PRs, or run factory workflows. The Lab mechanisms in a flow are the repo's own: `projects/<name>/check`, the factory Review under `factory/`, and human merge.

## Steps

1. Read `.claude/skills/workflow/scenarios.json`. Match the argument to a `key`: `small`, `medium`, `big`, `huge`, `poc`, `bug`, `unattended`.
2. No argument, or no match: ask the user once which scenario applies, listing each `key`, its `name` and its `when_to_use`. If you cannot ask (an unattended session), default to `medium` and make "Scenario defaulted to Medium: none was given" the first todo.
3. Start no work until a scenario is chosen.
4. Make one todo per entry in the scenario's `flow`, in order, using the `step` text as written. Then add a todo for its `proof`.
5. If the entry has a `branch`, add it as a todo after the flow steps; if it turns out not to apply, title it `skip: <reason>`.
6. Add one todo per `skip` entry, titled `skip: <step>: the <name> flow leaves it out`, and mark it completed at once.
7. A flow step you decide not to do (including an `optional` one) stays on the list, titled `skip: <reason>` with your own reason. Never delete it.
8. Treat a step as done only when its proof exists.
9. Then start the work, in order.

After the work, offer to write the workflow record: the scenario, each step done or skipped with a reason, and a link to its evidence. Do not write it unasked.
