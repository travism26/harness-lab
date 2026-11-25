# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those roles to the actual label strings used in this repo's issue tracker.

| Label in mattpocock/skills | Label in our tracker | Meaning                                  |
| -------------------------- | -------------------- | ---------------------------------------- |
| `needs-triage`             | `needs-triage`       | Maintainer needs to evaluate this issue  |
| `needs-info`               | `needs-info`         | Waiting on reporter for more information |
| `ready-for-agent`          | `ready-for-agent`    | Fully specified; an agent can build it. It does not start the factory |
| `ready-for-human`          | `ready-for-human`    | Issues only: requires human implementation. The factory never sets it |
| `wontfix`                  | `wontfix`            | Will not be actioned                     |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the corresponding label string from this table.

Starting the factory is a separate step. The owner adds `owner:implement` to a Spec, or to a hand-written Ticket. The factory App then adds `factory:start` to one eligible Ticket. `ready-for-agent` still does not start a build, on a laptop Ticket or a factory Ticket.

The factory's own labels are in [docs/factory/README.md](../factory/README.md#labels). All of them are defined in `factory/labels.json`. A label's prefix says who applies it: `owner:`, `builder:`, `scout:`, or `factory:`.
