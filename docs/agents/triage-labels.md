# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified; an agent can build it. It does not start the factory |
| `ready-for-human`          | `ready-for-human`    | Requires human implementation; the factory also adds it after two rework rounds |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Starting the factory is a separate, deliberate step: the owner adds `ready-for-factory`. A skill that applies `ready-for-agent` never starts a factory run.

The factory's own labels (`ready-for-factory`, `in-progress`, `rework`, `rework:1`, `rework:2`, `factory-check`) are in [docs/factory/README.md](../factory/README.md#labels). All of them are defined in `factory/labels.json`.
