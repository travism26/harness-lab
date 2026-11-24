# Goal: Experiment — does a Stop hook keep a Claude Code session open until the project check has run?

## For you

**What.** Write and validate an Experiment request, `experiments/stop-hook-requires-check/request.md`, that tests this claim: a committed Stop hook can keep a Claude Code session from ending as "done" until the relevant project `check` has been run and has passed in that session. The live `claude -p` run is started by the owner; the checks themselves call no model. This Experiment stays on a throwaway `experiment/stop-hook-requires-check` branch and a draft PR.

**Why.** We have not measured whether Claude Code actually honours a Stop-hook block on the owner's installed version. This Experiment is how we find out, with a cost cap and a revert path, before we rely on hooks on `main`.

**Done looks like.** A valid request, a hook script and fixtures used by the request's checks, and a draft PR from the throwaway branch. If a live run happened, `results.md` is filled in, including the client-estimated cost.

## For the agent

**Destination.** `experiments/stop-hook-requires-check/` only.

**Pass/fail checks** (3):

1. The experiment validator exits 0 on the request.
2. The request has a cost cap at or under $2, a timebox at or under 60 minutes, and a Revert that closes the draft PR and deletes the branch.
3. The Hypothesis is falsifiable: it says what would count as the hook not keeping the session open.

**Constraints.** Do not merge the experiment branch. Do not edit factory workflows.
