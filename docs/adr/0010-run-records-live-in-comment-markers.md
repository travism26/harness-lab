# Run records live in comment markers on the Ticket or pull request

A Factory run's cost, turns and tokens used to exist only in its uploaded artifact, which GitHub deletes after 90 days. Every Factory run now leaves one Run record, and the durable copy is a hidden `<!-- factory:run {...} -->` marker on exactly one comment the factory bot posts on the Ticket or pull request. The artifact's `run.json` is a convenience copy that expires.

A comment is an atomic append that needs no new permission, sits beside the work it describes, and is read with the `gh` calls the factory already makes. A branch of JSONL files would need a contents-write token in more steps and would have to settle push races between Review runs on different pull requests. Artifacts alone lose the numbers after 90 days. A database or a billing API is more than a hobby lab needs.

## Consequences

- A Factory run that posted no comment before (a Rework run, a failed Review, a Review that finishes on a closed pull request) now posts one plain line carrying its marker.
- Anyone can paste a marker into a comment, so a reader trusts only markers on comments the factory bot wrote.
- The step that writes the marker holds the App token and runs after the agent, so it treats the agent step's numbers as untrusted: known fields only, checked types, fixed vocabularies, and nothing that could close the HTML comment. It runs only the factory's own scripts (`docs/adr/0007-factory-scripts-from-the-default-branch-agents-without-github-token.md`).
- Factory runs from before the marker existed are backfilled into one committed JSONL file, not by editing old comments.
