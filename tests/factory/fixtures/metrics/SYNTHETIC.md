Tickets 17, 116, 127 and 128 are cut down from real API JSON. These are synthetic, in the same API shape, for cases the real Tickets do not show:

- `ticket-9001` (pull request 9002): merged; the bot added `rework:1` and the owner re-added `rework` and `rework:2` by hand; one owner commit; first CI run failed; reverted on main (`main-subjects.json`).
- `ticket-9003` (pull request 9004): closed unmerged; started under the old start label `ready-for-agent`.
- `ticket-9005` (pull request 9006): still open; first CI run not finished.
- `ticket-9007` (no pull request): claimed by the bot (its "started this Ticket" comment) and left no Run record, so it has a row with Draft `no`.
