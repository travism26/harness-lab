# The Review Verdict is a commit status, and an Override records its reason

A Review's Verdict used to exist only as a comment on the pull request, so nothing at the merge box showed it. Of 69 merged pull requests, 11 merged on a BLOCKED head and 15 with no Review of the final head, and no reason was written down for any of them. Review now sets a commit status, `factory/review`, on the head it read: success for PASS, failure for BLOCKED, and error with the reason when a Review ends without a Verdict. The owner can merge past it with an Override: a comment on the pull request that starts with `Override:` and gives the reason. A small owner-only workflow turns the status green, links the comment, and labels the pull request `review-override`.

GitHub's own ruleset bypass would let the owner merge past a required status, but it records no reason, which is the problem this decision is meant to fix. So the ruleset on `main` lists no bypass actors and the Override is the only way past. The status is set with the workflow's own token and `statuses: write`, in a step that runs no agent, because the factory App has no commit-status permission and does not need one. A check run was the alternative; a status is matched by name alone and is simpler to require.

The ruleset comes last. It is a repository setting the owner turns on once Review runs on every head and the Review's agreement with the owner has been measured. Until then the status and the Override show the Verdict and collect the reasons without stopping a merge.

## Consequences

- A status belongs to one commit, so a new push starts with none and cannot inherit an earlier PASS.
- Once the ruleset is on, a Review that is capped or fails holds the merge until it is re-run or overridden, and required statuses also block direct pushes to `main`.
- A pull request from a fork never gets a Review, so it needs an Override to merge.
- An Override applies to the head at the time of the comment. A later push needs a new Review or a new Override.
