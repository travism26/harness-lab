# The factory

The factory is the GitHub Actions setup that turns labelled Tickets into draft PRs against this
repository, with a review step on every PR. It builds the harness. From episode 1, every change is a
Ticket for the factory. The workflows are adapted from
[claude-code-adw PR 8](https://github.com/travism26/claude-code-adw/pull/8). That PR built the
labels, the review step and a rework trigger. This repo adds the steps that build a Ticket and run
a rework round.

Nothing runs until the owner has done the [setup guide](setup.md). Until then every factory run
fails with a message naming what is missing. It never goes green without doing anything.

## How a Ticket moves

1. The owner writes a Ticket (a GitHub issue), applies one `project:<name>` label and applies
   `ready-for-factory`. The label names the Project (`projects/<name>/`). The name is a safe slug:
   lowercase letters, digits and single hyphens. An existing Project has an executable
   `projects/<name>/check`, and that script, not a fixed command, is how its work is tested, in
   whatever language the Project uses. A Ticket with no `project:` label, more than one, an unsafe
   name, or a name that is not registered and has no executable `check` is refused before any agent
   runs: the factory comments why on the Ticket and removes `ready-for-factory`. A name that is
   already a row in `factory/labels.json` and has no `check` yet is how a Project starts. See
   [Starting a Project](#starting-a-project).
2. **Implement** (`.github/workflows/implement.yml`) claims it. It removes `ready-for-factory`, adds
   `in-progress` and comments with a link to the run. Claude Code builds the change in a fresh
   checkout; its prompt names `projects/<name>/` and tells it to run `projects/<name>/check` until it
   passes, and to read that Project's glossary and decision records. A Project with a `go.mod`
   already on the branch gets Go first, at the version its `go.mod` names (Rework does the same).
   The factory then commits it to `factory/issue-<N>`, pushes, and opens a **draft** PR
   whose body closes the Ticket. A new Project is the exception: before that commit, the factory
   itself runs the `check` the agent just wrote. See [Starting a Project](#starting-a-project).
3. **Review** (`.github/workflows/review.yml`) runs on the new PR. A fresh agent with read-only
   tools reviews the diff along two axes: Spec (does it do what the Ticket asks?) and Standards
   (does it follow `CLAUDE.md`, the glossaries and the decision records?). It posts one report on the PR.
4. **CI** (`.github/workflows/ci.yml`) runs on the PR with no secrets. When that run finishes,
   **CI gate** (`.github/workflows/ci-gate.yml`) runs from the default branch, and only for an open
   pull request whose branch is `factory/issue-<N>`, whose head repository is this one, and whose
   author is the factory App. A failure starts Rework only while the PR is still a draft. A fork,
   any other branch, or a PR the owner opened by hand is ignored.
   - A **failure** posts one comment with the review marker. The comment names each failed job and
     a short tail of its log, with secret values removed, and says the rework round must make the
     check pass. It then applies the same labels Review uses (`rework` and `rework:1`, then
     `rework:2`, then `ready-for-human`), with the App token, so **Rework** starts. `revise` reads
     that comment. Its `--run-url` is the rework run; the CI run's URL is in the comment.
   - If Review has already charged this head, the failure joins that round and the counter stays.
     If CI charged first, Review's Spec blocker joins the same way. One head, one round.
   - Rework waits until CI for that head has finished. A failure is included once the gate's
     comment names that run, so the agent sees the excerpt. `timed_out`, `cancelled` and `skipped`
     count as finished and do not wait for a comment. If no CI run exists for the head and Review
     is already ready, or CI has failed and the comment never arrives (the gate ignores a non-draft,
     a fork, or `ready-for-human`), Rework gives it two minutes and then continues. A repeated
     delivery of the same CI run does not open another round. If two charges land together, the
     later comment is rewritten so it does not claim the round.
   - A **green** run does nothing by itself. Once Review has passed that same head, and that head
     is not already in an open rework round, the gate removes `in-progress` from the Ticket and
     comments on the pull request and the Ticket. It does this even if the pull request is no
     longer a draft: the factory's work on that head is done either way. The pull request stays a
     draft unless a human has already marked it ready. A human merges it. No other step asks the
     owner to act. The gate's preflight checks the App and the daily cap. It does not require the
     Claude Code login, because it runs no agent.
5. If the Spec axis finds a blocker, Review labels the PR `rework` and `rework:1`, unless this
   head was already charged by CI. Review does not remove `in-progress`; the CI gate does that.
   The label starts **Rework** (`.github/workflows/rework.yml`).
   Claude Code fixes what the review named, including a CI failure in the comment, and pushes.
   The push starts Review and CI again.
6. A second blocker, from Review or from CI, labels the PR `rework:2` and starts a second rework
   round. The blocker after that labels the PR `ready-for-human`, and the factory stops: Review,
   Rework and the CI gate skip the PR from then on.
7. When Review has passed the current head and CI is green, the draft waits. The owner reads it,
   marks it ready and merges it. The merge closes the Ticket. `in-progress` is already gone, so
   the next Ticket can start without waiting for that merge.

## Starting a Project

A new Project is a Ticket whose `project:<name>` label is already a row in `factory/labels.json` on
the factory checkout, and whose `projects/<name>/check` is not an executable file there yet. Claim
records that as a bootstrap and starts the Ticket. The agent creates the Project tree, including
the check. Claim does not refuse the Ticket for the missing file. A `check` that is already there
but not executable is still refused: that is a half-written Project, not a new one.

Registering that row is the remaining manual step. A name that is not in the file, or is not a safe
slug, is still refused, so a typo cannot take the one-at-a-time lock or the build budget. The
factory does not add the row itself. `sync_labels` only creates labels that are already listed, and
an issue can only wear a label GitHub already has, so there is nothing to sync until the row is on
`main`. A row committed on the bootstrap pull request would not count either: Claim reads the
factory checkout, which is the default branch, or the pull request's base on a rework round, not
the pull request head.

What the owner does once:

1. Add a `project:<name>` row to `factory/labels.json`. The name is a safe slug, such as `ai-gateway`.
2. Merge that edit, then run `uv run python -m factory.sync_labels --apply` so GitHub has the label.
   Run it without `--apply` first to see the dry run.
3. Label the Ticket `project:<name>` and `ready-for-factory`.

From there it is automatic. The agent's prompt tells it to create `projects/<name>/`, including an
executable `check` that satisfies `CODING_STANDARDS.md`, and that it may edit `GLOSSARY-MAP.md` and,
when the Ticket adds a Python workspace member, the root `pyproject.toml` and `uv.lock`. It still
may not edit `.github/`. After the agent finishes, and only on a bootstrap, the job installs Go if
the new `go.mod` exists, the same way [CI](#ci) does (the same setup-go action, version file and
cache path), and then runs `projects/<name>/check`. That step has no App token and no Claude login.
A missing check, a check that is not executable, or a check that exits non-zero fails the job.
Publish does not run. Implement's existing failure step drops `in-progress`, and the Ticket can be
labelled again. On a Go Project the agent does not have Go during its own turn, because
`go.mod` appears during that turn. The factory installs Go afterwards and runs the check once. A
Python Project has `uv` for the whole turn, since Implement installs `uv` before the agent starts.

Rework of that pull request uses the same rule. The label row is on the base, so a round can start
before the check has merged, and the check runs from the pull request's branch. A failure leaves
the `rework` label, as any failed rework does.

Once `projects/<name>/check` is an executable file on the default branch, later Tickets for that
Project are ordinary. The prompt tells the agent to run the check. The factory does not run it
itself. CI runs it after the pull request opens, as for every other Project.

The one gate on the check is the owner's merge of that pull request. The factory only sees the
script's exit code. A script whose body is `exit 0` passes this step, and it passes CI. Review can
read the script and has no shell, so it cannot tell that script from a real test run. Merging is
what accepts the script as the Project's check. Every later Ticket is told to satisfy it.

## Brakes

Each brake, from the lab-wide [decision records](../adr/) (0003, 0004, 0005, 0007), and where it is enforced.

| Brake | Where |
|---|---|
| Draft PRs only | `factory/ticket.py` `publish` opens every PR with `--draft`. Nothing in the factory marks a PR ready or merges it. |
| A review step on every PR | `review.yml` runs on `opened`, `synchronize`, `reopened` and `ready_for_review` for every PR from a branch of this repo, draft or not, the owner's own PRs included. Fork PRs are the exception: see public-repo safety below. |
| Stop after two rework rounds per Ticket | `factory/review_pr.py`: `MAX_REWORK = 2`. The counter lives in the `rework:N` label. Review and the CI gate share it, one charge per head. The blocker after `rework:2` adds `ready-for-human`. |
| One Ticket at a time | `implement.yml` runs in one concurrency group, `factory-ticket`, which is never cancelled. `factory/ticket.py` `claim` refuses a Ticket while another open Ticket is labelled `in-progress`. The refusal is posted on the Ticket and `ready-for-factory` is removed. |
| A human merges | The App has no permission to merge or approve, and no step asks it to. |

Further limits:

- **Daily run cap.** The preflight stops a workflow once it has started `FACTORY_DAILY_RUN_CAP`
  runs that UTC day (default 20). `0` is a kill switch.
- **Dollar cap per agent run.** Claude Code's `--max-budget-usd` caps every agent run. A run that
  hits the cap fails red. The check happens between turns, so a run can go a few cents over.
- **The spend stop** is the credit limit on the OpenRouter key, enforced by OpenRouter
  ([ADR 0004](../adr/0004-per-key-credit-limits-as-the-spend-stop.md)). On the subscription
  token, the plan's own usage limits apply.

## Public-repo safety

From [ADR 0005](../adr/0005-label-only-factory-start-and-no-secrets-for-forks.md):

- **The factory starts only on a label the owner applies.** `implement.yml` and `factory-check.yml`
  run only when `github.event.sender.login` is the repository owner. Opening an issue starts
  nothing. `rework.yml` runs only on a `rework` label added by the factory App or the owner, and
  only on a `factory/*` branch. The CI gate adds that label with the App token, and only on a
  `factory/issue-<N>` draft the App opened.
- **Fork PRs never get secrets.** Every workflow that holds a secret skips PRs whose head is not this
  repository. `ci.yml` runs fork PRs' tests on plain `pull_request`, which holds no secrets. Fork PRs
  get CI only, and a human reviews them. `ci-gate.yml` is `workflow_run`, which can see secrets, so
  its job does not run unless the CI run's head repository is this one.
- **The factory's scripts come from the default branch.** Review and Rework run on
  `pull_request_target`, and the CI gate runs on `workflow_run`, so the workflow file and `factory/`
  come from the default branch. A PR cannot change the brake that judges it. The PR's code is
  checked out to a separate directory (`pr/` or `work/`). See [ADR 0007](../adr/0007-factory-scripts-from-the-default-branch-agents-without-github-token.md).
- **The agent never holds a GitHub token.** The steps that hold the App token (`claim`, `prepare`,
  `publish`, `apply`) run no agent. The agent step gets only its Claude Code login, through
  `factory/claude.py`, which drops every other credential from its environment. The checkouts keep
  no git credentials, so the agent cannot push. The new-project check is its own step, after the
  agent and before publish, and it gets neither the App token nor the Claude login: it runs a
  script the agent just wrote. Any secret value found in a run's files is redacted
  before they are posted or uploaded.
- **The reviewer reads PR content, so it gets no shell.** Review's agent has only Read, Grep and
  Glob, and cannot read `/proc`, so text in a PR cannot make it run anything or reveal its login.
  The build agent in Implement and Rework does have a shell, to run the tests. That means it can see
  its own Claude Code login. It works only from Tickets the owner labelled, and on the
  subscription token only from the owner's own Tickets (the switch rule).
- **The factory cannot change its own workflows.** The App has no Workflows permission, so a push
  that touches `.github/workflows/` is refused. Changes to the factory are made by hand.

## The Claude Code login and the switch rule

The factory's Claude Code runs on one of two logins. The repository variable `FACTORY_CLAUDE_LOGIN`
chooses which:

- `subscription` (the default): the owner's Claude subscription token, from `claude setup-token`,
  in the secret `CLAUDE_CODE_OAUTH_TOKEN`.
- `openrouter`: the OpenRouter key for GitHub runs, in the secret `OPENROUTER_API_KEY`. It goes
  through OpenRouter's Anthropic-compatible endpoint, `https://openrouter.ai/api`.

**The switch rule.** While only the owner's work is involved, the factory's Claude Code runs on the
owner's subscription token. It switches to an OpenRouter key before anyone else's issue or PR is
acted on, before an unattended scheduled job runs, or if it strains subscription usage.

To switch, set `FACTORY_CLAUDE_LOGIN` to `openrouter`. The code enforces the first two conditions
on the subscription token (`factory/switch_rule.py`):

- **Anyone else's issue or PR.** Every agent run checks the Ticket's author and the PR's author.
  If either is not the owner or the factory App, the run refuses to start and names the rule.
- **Scheduled jobs.** A scheduled run is refused on the subscription token. None exists yet. The
  daily groceries job (episode 4) must pass `scheduled=True`.
- **Strain on subscription usage.** This one is the owner's judgement. If factory runs eat into the
  plan's usage limits, switch.

The harness itself never uses the subscription token
([ADR 0002](../../projects/harness/docs/adr/0002-openrouter-only-provider-and-sole-credential.md)). This rule covers only the
factory's Claude Code.

## Pieces

| Piece | File |
|---|---|
| Label set and sync | `factory/labels.json`, `factory/sync_labels.py` |
| Preflight: configuration, daily cap, App token | `.github/actions/factory-preflight/action.yml` |
| Build a Ticket | `.github/workflows/implement.yml`, `factory/ticket.py` (`claim`, `build`, `verify`, `publish`, `release`) |
| Review step | `.github/workflows/review.yml`, `factory/review_pr.py` (`prepare`, `review`, `apply`) |
| Rework round | `.github/workflows/rework.yml`, `factory/ticket.py` (`revise`, `build`, `publish`) |
| CI failure and green settle | `.github/workflows/ci-gate.yml`, `factory/ci_gate.py` |
| Live check | `.github/workflows/factory-check.yml`, `factory/check.py` |
| Claude Code login | `factory/claude.py`, `factory/switch_rule.py` |
| CI check | `.github/workflows/ci.yml`, `factory/ci_projects.py` (see [CI](#ci)) |

## CI

`.github/workflows/ci.yml` runs on every PR and on every push to `main`, with no secrets and
`persist-credentials: false` ([ADR 0005](../adr/0005-label-only-factory-start-and-no-secrets-for-forks.md)).

1. The **factory tests** job always runs `uv run pytest tests/factory`.
2. That job then chooses which Projects to check (`factory/ci_projects.py`). It diffs the change
   against its base: a PR's base commit, or the commit before a push to `main`.
   - Each Project (`projects/<name>/` with a `check`) whose files changed is checked.
   - A change to `factory/`, `.github/` or the root `pyproject.toml` or `uv.lock` checks every Project,
     because they all depend on those.
   - With no base to diff against (a new branch's first push), every Project is checked.
   - A change that touches no Project and nothing shared checks no Project. Only the factory tests run.
3. A **check `<name>`** job runs `projects/<name>/check` for each chosen Project, in parallel. Every
   job gets uv. A Project with a `go.mod` also gets Go, at the version its `go.mod` names.

A failed run of this workflow on a `factory/issue-<N>` draft is a rework input. The gate posts the
failed job's name and a redacted log excerpt as a review comment and enters Rework. See [How a
Ticket moves](#how-a-ticket-moves).

## Labels

| Label | Who adds it | Meaning |
|---|---|---|
| `ready-for-factory` | Owner | Start the factory on this Ticket |
| `in-progress` | Factory | The factory is building or reworking this Ticket. Removed when Review has passed the current head and CI is green, so a finished draft does not hold the one-at-a-time lock. |
| `rework`, `rework:1`, `rework:2` | Factory (Review or CI gate) | A Spec blocker or a failed required CI run; the counter is the rework round, one charge per head |
| `ready-for-human` | Factory (Review or CI gate) | Two rework rounds were not enough; the factory has stopped |
| `project:<name>` (for example `project:harness`) | Owner | The Project the Ticket builds. The row is in `factory/labels.json`. See [Starting a Project](#starting-a-project) |
| `factory-check` | Owner | Run the live check |
| `ready-for-agent` | Owner or a skill | Triage only: fully specified. It does not start the factory, so a Ticket can carry it and still be built on the laptop |
| `needs-triage`, `needs-info`, `wontfix` | Owner | Triage, see [triage-labels.md](../agents/triage-labels.md) |

To change a label, edit `factory/labels.json` and run
`uv run python -m factory.sync_labels --apply`. Run it without `--apply` first to see the dry run.
It never deletes a label.

## Knobs

All are repository variables. Defaults apply when a variable is unset.

| Variable | Default | Meaning |
|---|---|---|
| `FACTORY_CLAUDE_LOGIN` | `subscription` | `subscription` or `openrouter`: see the switch rule |
| `FACTORY_DAILY_RUN_CAP` | `20` | Runs per workflow per UTC day. `0` stops every run. |
| `FACTORY_BUILD_MODEL` | `sonnet` | Model for Implement and Rework: `haiku`, `sonnet` or `opus` |
| `FACTORY_BUILD_BUDGET_USD` | `5` | `--max-budget-usd` for one Implement or Rework run |
| `FACTORY_REVIEW_MODEL` | `sonnet` | Model for Review |
| `FACTORY_REVIEW_BUDGET_USD` | `2` | `--max-budget-usd` for one review |

The workflows pin the Claude Code version in `CLAUDE_CODE_VERSION` at the top of each file.

## When something stops

| What you see | What to do |
|---|---|
| A comment says the factory did not start the Ticket | Read the reason. For "one Ticket at a time", finish or close the other Ticket. For "switch rule", switch to `openrouter`. Then re-apply `ready-for-factory`. |
| A comment says the factory run failed | Open the run. A new Project whose `check` was missing or failed looks like this. The Ticket has lost `in-progress`, so it can be retried. |
| A factory PR is closed without merging, and `in-progress` is still on the Ticket | Review had not passed that head with green CI (a red CI run, a Spec blocker, or a closed PR). Remove `in-progress` by hand, or one-at-a-time keeps every other Ticket waiting. |
| A factory draft's CI is red and no rework starts | Open the CI gate run. It ignores a PR that is not a draft, not opened by the factory App, or not on `factory/issue-<N>`, and it stops at the daily cap. A `timed_out` or `cancelled` CI run is not a failure. |
| A PR is labelled `ready-for-human` | Finish it by hand, or close it. The factory will not touch it again. |
| A Rework run failed | The PR keeps `rework`. Fix it by hand and push, or re-add `rework` to retry. |

## Not built yet

- **The episode notes step.** At the end of an episode the factory writes episode notes from
  [the template](../../projects/harness/docs/episodes/TEMPLATE.md). For now this is a Ticket like any other.
- **Retries after the concurrency queue.** GitHub keeps one pending run per concurrency group. If
  the owner labels three Tickets at once, the middle one's run is dropped and its label stays. Label
  one Ticket at a time.
- **Third-party actions are pinned by tag**, not by commit SHA.
