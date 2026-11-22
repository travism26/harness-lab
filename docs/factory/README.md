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

1. The owner writes a Ticket (a GitHub issue) and applies `ready-for-factory`. A Ticket with no
   `project:` label is factory-root work, scored by the factory tests (`uv run pytest tests/factory`).
   A Project Ticket is unchanged: it also carries one `project:<name>` label. The label names the
   Project (`projects/<name>/`). The name is a safe slug: lowercase letters, digits and single
   hyphens. An existing Project has an executable `projects/<name>/check`, and that script, not a
   fixed command, is how its work is tested, in whatever language the Project uses. A Ticket with
   more than one `project:` label, an unsafe name, a name that is not registered and has no
   executable `check`, or a `check` that is not executable, is refused before any agent runs: the
   factory comments why on the Ticket and removes `ready-for-factory`. A name that is already a
   row in `factory/labels.json` and has no `check` yet is how a Project starts. See
   [Starting a Project](#starting-a-project).
2. **Implement** (`.github/workflows/implement.yml`) claims it. It removes `ready-for-factory`, adds
   `in-progress` and comments with a link to the run. Claude Code builds the change in a fresh
   checkout under `work/`. The factory's own scripts stay in the checkout at the workspace root,
   which is a second copy of the repository, and publish commits only `work/`. Before the agent
   starts, the Ticket is copied to `work/.factory/ticket.md` (a rework round also copies the
   review to `work/.factory/review.md`) and the prompt names those paths. `/.factory/` is in the
   root `.gitignore`, and the factory writes the same line into the work checkout's
   `.git/info/exclude`, so a branch cut before the gitignore line still does not commit the copy.
   An absolute path under `run-out/` points at the factory's own checkout, and an agent that follows
   it edits that checkout, which publish never commits. For a Project Ticket the prompt names
   `projects/<name>/` and tells it to run `projects/<name>/check` until it passes, and to read that
   Project's glossary and decision records. For factory-root work the prompt tells the agent to run
   `uv run pytest tests/factory` until it passes, and to limit edits to the factory package, its
   tests, the factory doc, the lab glossary, the glossary map, the lab decision records and the root
   gitignore. It does not name a Project folder or a `projects/<name>/check`, and the run is not a
   bootstrap, so the factory does not run a new-project check. A Project with a `go.mod` already on
   the branch gets Go first, at
   the version its `go.mod` names (Rework does the same). Rework of a factory-root Ticket uses the
   same prompt.
   The factory then commits it to `factory/issue-<N>`, pushes, and opens a **draft** PR
   whose body closes the Ticket. If the agent finishes and the work checkout is unchanged,
   publish fails. The failure comment on the Ticket says so, includes the agent's summary, and
   lists any edits it finds in the factory checkout outside `work/`. A new Project is the
   exception: before that commit, the factory itself runs the `check` the agent just wrote. See
   [Starting a Project](#starting-a-project).
3. **Review** (`.github/workflows/review.yml`) runs on the new PR. A fresh agent with read-only
   tools reviews the diff along two axes: Spec (does it do what the Ticket asks?) and Standards
   (does it follow `CLAUDE.md`, the glossaries and the decision records?). It posts one report on the PR.
4. **CI** (`.github/workflows/ci.yml`) runs on the PR with no secrets. When CI or Review
   finishes, **CI gate** (`.github/workflows/ci-gate.yml`) runs from the default branch, and only for an open
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
     count as finished and do not wait for a comment. The wait itself stops at its timeout
     (two minutes for a failure with no comment or no CI run; twenty minutes at the outside)
     and Rework continues. If no CI run exists for the head and Review
     is already ready, or CI has failed and the comment never arrives (the gate ignores a non-draft,
     a fork, or `ready-for-human`), Rework gives it two minutes and then continues. A repeated
     delivery of the same CI run does not open another round. If two charges land together, the
     later comment is rewritten so it does not claim the round.
   - A **green** CI run does nothing by itself. The gate runs again when Review finishes. If CI
     for that head is already green and the new Review comment is PASS, and the head is not
     already in an open rework round, the gate removes `in-progress` from the Ticket. It does
     not post a separate comment for that. It does this even if the pull request is no
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

## Research path

A second way into the same factory. The owner asks one question, and the factory answers with a
cited Research note on a draft PR. It builds nothing. `.github/workflows/research.yml` runs it and
`factory/research.py` holds its steps. The workflow has three jobs, so that no step in the agent's
job holds a GitHub write token.

1. The owner opens a Research request from the issue template
   (`.github/ISSUE_TEMPLATE/research-request.md`). Its headings are `Question`, `Scope`,
   `Public starting points`, `Cost cap (USD)` and `Out of scope`. The owner then applies
   `ready-for-research`. The workflow starts only when `github.event.sender.login` is the
   repository owner, the label is `ready-for-research`, and the item is an issue, not a pull
   request. Opening the issue starts nothing.
2. **claim** holds the App token and runs no agent. It runs the preflight and refuses for the
   reasons Implement does: a closed Ticket, the switch rule, or another Ticket `in-progress`. It
   also refuses a request with a missing heading, an empty `Question`, `Scope` or `Out of scope`,
   a starting point that is not `https://`, a credential-shaped string, or a cost cap above the
   knob. A refusal is a comment on the Ticket, and the label is removed. Otherwise claim replaces
   `ready-for-research` with `in-progress`.
3. **research** runs the agent. The job gets the Claude Code login through `factory/claude.py`
   and nothing else. Its tools are Read, Grep, Glob, WebFetch and WebSearch. It has no shell and
   no write tool: the lists are Review's (`factory/review_pr.py`), with the two web tools moved
   from denied to allowed. The agent's reply is the note. The App token is never minted in this job.
4. **publish** holds the App token and runs no agent. First, in a step with no token, it writes
   the note's `Cost` section itself (the CLI's own list-price figure, marked `client-estimate`,
   and the run's cap) and runs the deterministic check, `factory/research_note.py`. The check
   requires the five sections of `docs/research/notes/_template.md`, at least one `https://`
   source, one `[vendor]` or `[independent]` tag on every source, an `Unknowns` section that says
   something, spend at or under the cap, and no credential-shaped string. Only a note that passes
   reaches the next step. That step commits the one file `docs/research/notes/issue-<N>.md` to
   the branch `research/issue-<N>`, opens a **draft** PR whose body closes the Ticket, comments on
   the Ticket with the link, and removes `in-progress`.
5. Review runs on the draft, as it does on every PR from a branch of this repo. The CI gate
   ignores the branch, and Rework starts only on `factory/*`, so a Spec blocker leaves its labels
   and report on the PR and no rework round starts. No agent merges the PR. The owner reads it and
   merges or closes it. Closing the PR and deleting the branch undoes the run.

**When it stops.** If the agent fails, the note fails its check, or the push fails, the run is
red and no PR is opened. The factory comments on the Ticket and removes `in-progress`. For a
failed check the comment lists the check's problems, which name sections and line numbers and
never quote the note. There is no rework round on this path. The owner changes the request and
applies `ready-for-research` again. Retry by relabelling, not by re-running the failed job: each
run attempt names its own artifacts.

**Budget.** The agent runs with `--max-budget-usd` from `FACTORY_RESEARCH_BUDGET_USD` (default
`2`). A request can set a lower cap under `Cost cap (USD)`. A higher one is refused before any
agent runs. A run that hits the cap fails red and publishes nothing.

**One at a time.** The workflow shares Implement's `factory-ticket` concurrency group and the
`in-progress` lock, so a research run and a build never overlap on the Claude Code login. The
research path holds the lock only while its run lasts.

**Public sources, no secrets.** A request and a note hold public material only: no private notes,
no email, no employer or customer material, and never a secret. The issue and the PR are public.
The check refuses a credential-shaped string in either one.

**What the check does not do.** It cannot tell whether a source supports the finding that cites
it. Review reads the note against the request, and the owner's merge is the gate.

**What the agent can reach.** The agent reads web pages nobody here wrote, and it can make web
requests, so a page can try to talk it into sending something out. The repository is public and
the agent's job holds no App token. The one secret within reach is its own Claude Code login, in
its own environment. As in Review, it has no shell and the rule `Read(//proc/**)` denies the
file where that environment is readable.

**Run record.** A research run that started its agent is a Factory run. Its record has
`workflow: research` and goes on the Ticket the way Implement's does: on the "opened a draft PR"
comment or the "failed" comment. A note that failed its check has `reason: check-failed`. The
metrics report lists build Tickets only, so a Research request has no row there.

**Not run yet.** No research run has happened on GitHub. The checker and the steps are proven on
fixtures and fakes. Before the first run the owner merges the PR that adds the workflow and runs
`uv run python -m factory.sync_labels --apply`, so GitHub has `ready-for-research`. The docs say
the web tools need no shell; the first live run is what confirms it. Whether WebSearch works on
the `openrouter` login is not known.

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
| Research path | `.github/workflows/research.yml`, `factory/research.py` (`claim`, `answer`, `check`, `publish`, `release`), `factory/research_note.py` (the note check). See [Research path](#research-path) |
| Live check | `.github/workflows/factory-check.yml`, `factory/check.py` |
| Claude Code login | `factory/claude.py`, `factory/switch_rule.py` |
| Run record | `factory/record.py` (the fields, the checks, the marker), `factory/run_record.py` (`write`) and `factory/run_record_review.py`, the last step of `.github/workflows/implement.yml`, `.github/workflows/rework.yml` and `.github/workflows/review.yml` |
| CI check | `.github/workflows/ci.yml`, `factory/ci_projects.py` (see [CI](#ci)) |

The owner runs one Bench tracer, no model call and no GitHub call: `uv run python -m factory.bench --case CASE.json --setup-id ID --harness-command CMD --review-answer-file tests/factory/review-answer.json`.

The owner replays the two committed Bench cases (Tickets 8 and 9, `factory/bench_cases/`) with `uv run python -m factory.bench --replay`: three Bench runs of each, one at a time, under the Setup `claude-code-sonnet`, then a report (passed out of 3, unstable, cost min, median and max; no ranking). Its first line says the run is not comparable while a newer checkout of this repo is readable. It names four owner steps: the API key (`ANTHROPIC_API_KEY`), a provider-side monthly limit if the console has one, Claude Code `2.1.319` on `PATH`, and a machine that cannot read a newer checkout. Without the key, or with another `claude --version`, the command refuses before any clone and prints the install line (`npm install -g @anthropic-ai/claude-code@2.1.319`) without running it. The first live run is an owner step; the tests call no model.

## Run records

A Run record is the one small JSON object a Factory run leaves behind: what ran (workflow, run id, attempt), on which Ticket and pull request, with which login, model alias and budget cap, how it ended (`outcome` `ok` or `fail`, and for a failure a `reason` from a fixed list), and what it cost (dollars, turns, the four token counts, duration). It holds facts and numbers, never text from the model. The dollars are the CLI's own list-price estimate on every login, so the record marks them `client-estimate`.

It lives in two places. The durable copy is a hidden `<!-- factory:run {...} -->` marker appended to the comment the run already posted on the Ticket (the "opened a draft PR" comment, or the "failed" comment), so it lasts as long as the Ticket. A cancelled run posts neither comment, so its record goes on one plain line the last step posts. A marker counts only as the whole final line of a bot comment, which is where the last step writes it; a copy anywhere else in a comment is somebody's quotation and is never read as a record. The places that put model text into a bot comment (the review report's summaries and findings, the agent's summary in the "failed" comment, and the live check's reply) put a zero-width space inside `<!--` and `-->`, so that text cannot form a marker either and a quoted `<!--` still reads. The other copy is `run-out/run.json` in the run's uploaded files, which GitHub deletes after 90 days. The decision is in [ADR 0010](../adr/0010-run-records-live-in-comment-markers.md).

`factory.ticket build` saves only the raw numbers from the CLI's result line to `run-out/result.json`. The last step of `.github/workflows/implement.yml` (`factory.run_record write`) runs whenever the agent step started, holds the App token, and trusts nothing the agent step wrote: the run's identity comes from the workflow's context, it copies only known fields from `result.json`, checks each one's type, writes a field that fails its check as null with a workflow warning, and never puts `-->` or a token-shaped string in the marker; one last check of the whole serialized line, before it is posted, enforces that, and a line that fails posts no marker and warns. A count in `usage` of the wrong type is null; the token counts are summed from `modelUsage` only when `usage` is well-typed and all zero, which is what the CLI reports when it stops at its budget cap. It finds its comment among the bot's own comments on the Ticket, never from a file. Rework has no comment of its own, so its last step (`factory.run_record write --workflow rework`) posts one plain line on the pull request, for example "Rework round 1 pushed `abc1234`." or "Rework round 1 failed: `no-change`.", with a link to the run, and the marker on a second line. `round` and `pr` come from the workflow's context (the event's pull request and its `rework:N` label when the run started; when the event's labels hold no `rework:N`, the pull request's labels read at the end of the run), never from `run-out/`. `issue` is the number in the head branch `factory/issue-<N>`, and null for any other branch. A Rework run refused before its agent starts leaves no record.

Each last step sets `LOGIN` in its own `env:` from the repository variable `FACTORY_CLAUDE_LOGIN` instead of reading the job's `env`. `CLAUDE_CODE_VERSION` it still reads from the job's `env`. `factory/claude.py` removes the GitHub token, the Claude secrets and every `ANTHROPIC_*` variable from the agent's environment, but it does not remove `GITHUB_ENV`, so the agent's process holds the path of the file a step writes to change the environment of the steps after it. A value the agent wrote there would reach the last step through the job's `env`. The record's `claude_code_version` is therefore what the workflow's env said, checked only to be shaped like `1.2.3`; it is not a measurement of the CLI that ran.

Review's last step (`factory.run_record write --workflow review`, in `.github/workflows/review.yml`) runs whenever the Review step started. `factory.review_pr review` saves the same raw numbers to `review-out/result.json`, even when the agent fails. The marker is appended to the report comment, after its first two lines (the review marker and the gate line), which stay as they were. `verdict` and `gate` are read back from GitHub, not from `review-out/`: from the bot's own report for the reviewed head (its gate line and the sentence under the headline), with `round` from the pull request's `rework:N` label, `issue` from the Ticket its body closes (null when it closes none) and `project` from that Ticket's `project:<name>` label (null when there is no Ticket or no single such label). The one exception is a pull request that closed before `apply` ran: it has no report, so the verdict comes from `findings.json`, reduced to `PASS` or `BLOCKED`, and `gate` is `closed`. When no report was posted, the step posts one plain line with the marker and a link to the run, never with the review marker: "Review failed: `error_max_budget_usd`." for a failed Review (`reason` is a CLI error subtype, `no-result`, `unparsed-findings` or `cancelled`), or "Review finished after this pull request closed: PASS. Nothing was changed." for a closed one. Review of your own branches leaves a record too.

If a job hits `timeout-minutes`, GitHub cancels it, and GitHub's cancellation docs say a step whose condition is `always()` keeps running, within a five minute limit. No run of this repo has timed out yet, so a timed-out run leaving a record is documented but untested.

### Backfill

`uv run python -m factory.backfill --repo OWNER/NAME` builds a record for each past Implement, Rework and Review run whose agent started, from the artifacts GitHub still holds, and writes them to `factory/run-records-backfill.jsonl` (`--out` changes the path). Run it before the earliest artifacts expire on 2027-02-05. Each record has `backfilled: true`, its `ts` comes from the run, and the file is ordered by run id then attempt, so a second run gives the same bytes. Old artifacts predate `result.json`, so the numbers come from the transcript's closing result line, read through the same number-only path the factory uses. The download goes to a fresh temp directory (`--scratch` overrides it; one inside the repo is refused) and is deleted as soon as the record is built. A run with no artifact still gets a record with null numbers. `login`, `model`, `budget` and `claude_code_version` are null, since an old run did not leave them. `verdict`, `gate` and a Review's `round` come from the bot's report comment where one exists (a report from before the gate line is matched by the 12-character head it names and its gate read from its sentence; the verdict must be exactly PASS or BLOCKED), and a Rework's `round` from the bot's charging comments. Old comments are not edited. The command prints how many records have numbers and how many do not.

A failed run's `reason` comes from the jobs the command already fetches: a failed check step is `check-failed`; a failed publish step is `no-change` when the bot's "failed" comment for that run says nothing changed, and `publish-failed` otherwise; a Review step that failed after a `success` result line is `unparsed-findings`; a cancelled run is `cancelled`. The reason is null when nothing establishes it. A Review whose report charged nothing gets the round in force when it ran (the highest the bot had charged before it, or 0). A Review whose artifact is gone has no `head_sha`, so its report is the bot's report comment on the pull request created between the run's start and end. An Implement run whose artifact is gone takes its `issue` from the bot's comment that links the run's URL; with no such comment its `issue` is null. A Rework run's `no-change` cannot be told from `publish-failed`, because Rework posts no "failed" comment.

### Metrics report

`uv run python -m factory.metrics --repo travism26/harness-lab` prints a markdown table, one row per factory Ticket and a totals row. A factory Ticket is one the factory bot claimed, under either start label, or one an Implement Run record names (a record proves a claim). The claim is the bot's own comment on the Ticket that starts with "The factory started this Ticket." (a comment anyone else wrote, or one that only quotes that text, does not count), found among the comments the report already reads. A claimed Ticket whose run left no record gets a row with Draft `no`. It reads every comment through `gh`, trusts a marker only as the final line of a comment the factory bot wrote (`--app-slug`, default `OWNER-factory` from `--repo`), keys records by run id plus attempt so every attempt's cost counts, refuses a record whose `schema` it does not know, and also reads `factory/run-records-backfill.jsonl` when that file exists. It makes no model call. The columns:

| Column | Definition |
|---|---|
| Draft | The Ticket's Implement record has a `pr`. The total is over all factory Tickets, claimed or recorded. |
| First-pass review | The `verdict` of the first Review record for the pull request. The total is the share of PASS over Tickets that opened a draft. |
| Cost (estimate) | The sum of `cost_usd` across the Ticket's records, with the login, always an estimate. |
| Agent time | The sum of `duration_ms` across the Ticket's records. |
| Rework rounds | The highest `rework:N` label the bot added, read from the Ticket's and the pull request's timelines. A label added by anyone else, such as a hand re-add of `rework`, does not count. The total is the sum. |
| Owner commits | Commits on the pull request not authored by the bot. The total is the sum. |
| Human escalation | The bot added `ready-for-human`. |
| CI on first push | The first run of the CI workflow on `factory/issue-<N>` concluded `success`. Review runs and the CI gate are not CI. A branch with no CI run shows `none`, an unfinished first run `pending`; neither is a success. |
| Start label to draft | From the bot removing the start label (`ready-for-factory`, or `ready-for-agent` before 2026-11-08), taking the last removal at or before the pull request's creation, to that creation. The total is the median. |
| Merge | `merged`, `closed` (unmerged) or `open`. The total is merged over merged plus closed; an open pull request counts toward neither. |
| Untouched merge | Merged with no owner commit and never labelled `ready-for-human` by anyone, the bot or a person. Human escalation stays the bot's alone. |
| Post-merge reverts | Subjects of commits on `main` that start with `Revert` and name the merged pull request as `#<N>`. The total is the sum. |

Every rate in the columns from Rework rounds on is over factory Tickets that opened a draft, except Merge. A Ticket with no draft shows `-`. Labels, pull requests, commits and CI runs are read per draft through `gh`, because the CI gate can charge a rework round or hand a pull request to a human and it is not a Factory run. Commit subjects on `main` are read through the commits API for the `--repo` repository, not a local clone, which may be stale.

`--fixtures DIR` reads a directory of `ticket-<N>/` (`issue-comments.json`, `pr-comments.json`, `issue-timeline.json`, `pr-timeline.json`, `pr.json`, `pr-commits.json`, `ci-runs.json`) and a top-level `main-subjects.json` instead of GitHub, and `--backfill FILE` reads a backfill file. A fixtures directory holding a token-shaped string is refused. `tests/factory/fixtures/metrics/` holds fixtures cut down from real API JSON (prose replaced by placeholders, markers built by `factory/record.py`) and the golden table `tests/factory/fixtures/metrics/golden.md`. `ticket-9001`, `ticket-9003`, `ticket-9005` and `ticket-9007` are synthetic (see `tests/factory/fixtures/metrics/SYNTHETIC.md`).

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
| `ready-for-research` | Owner | Start the factory's research path on this Research request. See [Research path](#research-path) |
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
| `FACTORY_RESEARCH_MODEL` | `sonnet` | Model for the research path |
| `FACTORY_RESEARCH_BUDGET_USD` | `2` | `--max-budget-usd` for one research run. A Research request can set a lower cap, never a higher one. |

The workflows pin the Claude Code version in `CLAUDE_CODE_VERSION` at the top of each file.

## When something stops

| What you see | What to do |
|---|---|
| A comment says the factory did not start the Ticket | Read the reason. For "one Ticket at a time", finish or close the other Ticket. For "switch rule", switch to `openrouter`. Then re-apply `ready-for-factory`. |
| A comment says the factory run failed | Open the run. A new Project whose `check` was missing or failed looks like this. The Ticket has lost `in-progress`, so it can be retried. |
| A factory PR is closed without merging, and `in-progress` is still on the Ticket | Review had not passed that head with green CI (a red CI run, a Spec blocker, or a closed PR). Remove `in-progress` by hand, or one-at-a-time keeps every other Ticket waiting. |
| A factory draft's CI is red and no rework starts | Open the CI gate run. It ignores a PR that is not a draft, not opened by the factory App, or not on `factory/issue-<N>`, and it stops at the daily cap. A `timed_out` or `cancelled` CI run is not a failure. |
| A comment says the factory did not start the research request | Read the reason, fix the request or wait for the other Ticket, then re-apply `ready-for-research`. |
| A comment says the note failed its check | No PR was opened and `in-progress` is gone. The comment lists what the check found. Change the request if that helps, then re-apply `ready-for-research`. |
| A PR is labelled `ready-for-human` | Finish it by hand, or close it. The factory will not touch it again. |
| A Rework run failed | The PR keeps `rework`. Fix it by hand and push, or re-add `rework` to retry. |

## Not built yet

- **The episode notes step.** At the end of an episode the factory writes episode notes from
  [the template](../../projects/harness/docs/episodes/TEMPLATE.md). For now this is a Ticket like any other.
- **Retries after the concurrency queue.** GitHub keeps one pending run per concurrency group. If
  the owner labels three Tickets at once, the middle one's run is dropped and its label stays. Label
  one Ticket at a time.
- **Third-party actions are pinned by tag**, not by commit SHA.

## Rules from hand-fixes

Each entry is a mistake fixed by hand, and the check that now catches it. Append the next one here.

- A turn cap below 1 is accepted (the Run stops at once and calls no model). Ticket [#9](https://github.com/travism26/harness-lab/issues/9), PR [#24](https://github.com/travism26/harness-lab/pull/24), owner commit [`d1b8a68`](https://github.com/travism26/harness-lab/commit/d1b8a68cee42e5b10a221c3c3cf576d2550bd0da). Check: `test_turn_cap_below_one_rejected_from_flag` and `test_turn_cap_below_one_rejected_from_env`, run by `projects/harness/check`.
- A `pyproject.toml` under `projects/` is not a uv workspace member. Ticket [#17](https://github.com/travism26/harness-lab/issues/17), PR [#20](https://github.com/travism26/harness-lab/pull/20), owner commit [`cd26251`](https://github.com/travism26/harness-lab/commit/cd262518a375574808baaeee8ab254dc3e36281d). Check: `tests/factory/test_workspace_members.py`, run by `uv run pytest tests/factory`.
- The `revise` parser had no `--run-url`, though the rework-refusal path read `args.run_url`, so a real refusal crashed before it could comment on the Ticket; tests that built the arguments by hand hid it. Ticket [#18](https://github.com/travism26/harness-lab/issues/18), PR [#112](https://github.com/travism26/harness-lab/pull/112), owner commit [`a4368e5`](https://github.com/travism26/harness-lab/commit/a4368e5). Check: `test_every_flag_a_handler_reads_is_defined_by_its_parser`, `test_hand_built_arguments_carry_only_flags_the_parser_defines` and `test_revise_refusal_through_the_parser_with_the_workflow_flags` in `tests/factory/test_ticket_parser.py`, run by `uv run pytest tests/factory`.
