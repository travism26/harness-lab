# Python comment audit

This is a one-time reading of every `#` comment line that `factory/comment_ratchet.py` counts in the tracked Python files (`git ls-files '*.py'`). This pass deletes nothing, files no issue and adds no ADR. The category is a judgment made in the pull request that added the row, and the test checks coverage and spelling, not the judgment. This file is not a Retro and not a Research note.

| Category | When it is this | Suggested action |
| --- | --- | --- |
| Tautology | The line restates the code a reader can already see. A repo-root path that `CODING_STANDARDS.md` requires is not a Tautology when the path is the point of the line. | delete later |
| Stale | The line names a behavior, date, label, file, or constraint the current code and docs do not match. When two categories could fit and the line is false now, it is Stale. | delete later |
| Excuse | The line apologises for a hack, a workaround, a copy, or a special case, and the code could be changed so the line would go. | fix later |
| Decision Record | The line records a choice a reader would otherwise redo or undo. A pointer at an ADR or a repo-root path can be this. | keep |

To keep it in step: a deletion that should merge runs `uv run python -m factory.comment_ratchet update` to lower `factory/comment_baseline.txt` and removes the row here; a reword updates the row's text and leaves the baseline as it was; a new comment fails the ratchet before a row can be added.

Each row in the block below is `path`, category, action and the comment text, separated by tab characters. The text is what the ratchet counts: the text after `#`, one leading space removed, trailing whitespace removed. Rows follow the order of `git ls-files`, then source order within a file, with no line numbers.

```comment-audit
experiments/clickhouse-podcast-analytics/scripts/bench.py	Decision Record	keep	wait_end_of_query makes the summary header final (otherwise it is sent early).
experiments/clickhouse-podcast-analytics/scripts/bench.py	Decision Record	keep	most-mentioned brand in the default generated data
experiments/clickhouse-podcast-analytics/scripts/bench.py	Tautology	delete later	warm-up
experiments/clickhouse-podcast-analytics/scripts/ch.py	Decision Record	keep	Server may be restarting right after the init scripts ran.
experiments/clickhouse-podcast-analytics/scripts/generate.py	Decision Record	keep	distinct download_ids, redeliveries come on top
experiments/clickhouse-podcast-analytics/scripts/generate.py	Tautology	delete later	--- dimensions -------------------------------------------------------
experiments/clickhouse-podcast-analytics/scripts/generate.py	Decision Record	keep	Episodes sorted by publish time, so the episode index is also a time rank.
experiments/clickhouse-podcast-analytics/scripts/generate.py	Decision Record	keep	Campaigns: 14-60 days, fully inside the data window.
experiments/clickhouse-podcast-analytics/scripts/generate.py	Tautology	delete later	(brand, start_ts, end_ts_exclusive)
experiments/clickhouse-podcast-analytics/scripts/generate.py	Tautology	delete later	--- brand_mentions ---------------------------------------------------
experiments/clickhouse-podcast-analytics/scripts/generate.py	Decision Record	keep	40% of mentions come from campaign windows (brand fixed, episodes published
experiments/clickhouse-podcast-analytics/scripts/generate.py	Decision Record	keep	inside the window); the rest follow overall brand and podcast popularity.
experiments/clickhouse-podcast-analytics/scripts/generate.py	Decision Record	keep	arrival order should not be sorted by time
experiments/clickhouse-podcast-analytics/scripts/generate.py	Tautology	delete later	--- downloads --------------------------------------------------------
experiments/clickhouse-podcast-analytics/scripts/generate.py	Decision Record	keep	At-least-once delivery: ~1% of rows arrive a second time in later inserts.
experiments/clickhouse-podcast-analytics/scripts/generate.py	Decision Record	keep	ingested_at defaults to now(), so the redelivered copy is the newer version.
experiments/clickhouse-podcast-analytics/scripts/generate.py	Tautology	delete later	--- transcript segments ---------------------------------------------
experiments/experiment.py	Excuse	fix later	Same family as the token pattern in factory/record.py; a separate copy, built from
experiments/experiment.py	Excuse	fix later	pieces so this file does not match it.
experiments/experiment.py	Tautology	delete later	--- data ---------------------------------------------------------------------------
experiments/experiment.py	Decision Record	keep	"pass" | "fail" | "not run"
experiments/experiment.py	Tautology	delete later	--- ceilings -----------------------------------------------------------------------
experiments/experiment.py	Tautology	delete later	--- credential deny-list -----------------------------------------------------------
experiments/experiment.py	Tautology	delete later	--- parsing ------------------------------------------------------------------------
experiments/experiment.py	Tautology	delete later	name, blocks, prose
experiments/experiment.py	Decision Record	keep	Reported alone: every other message quotes the file, and none may echo the string.
experiments/experiment.py	Tautology	delete later	--- runner -------------------------------------------------------------------------
experiments/experiment.py	Decision Record	keep	a process outside the group holds the pipe
experiments/experiment.py	Decision Record	keep	whatever the check left running in the background
experiments/experiment.py	Tautology	delete later	--- results ------------------------------------------------------------------------
experiments/experiment.py	Tautology	delete later	--- CLI ----------------------------------------------------------------------------
experiments/experiment.py	Decision Record	keep	before the checks, which may write files
factory/backfill.py	Stale	delete later	The first words of each workflow's agent step, and of the steps that explain a failure.
factory/backfill.py	Decision Record	keep	neither fails at its publish
factory/backfill.py	Decision Record	keep	the result line went with the artifact
factory/backfill.py	Decision Record	keep	null identity fields would each warn
factory/bench.py	Decision Record	keep	Never in the stand-in's environment (docs/adr/0011-bench-spends-on-a-metered-api-key.md).
factory/bench.py	Tautology	delete later	---- ledger ----------------------------------------------------------------
factory/bench.py	Decision Record	keep	atomic: the lock never exists empty
factory/bench.py	Tautology	delete later	---- the run ---------------------------------------------------------------
factory/bench.py	Decision Record	keep	the agent's failure, or a malformed result line, is a Review error; keep the trace
factory/bench.py	Tautology	delete later	---- replay ----------------------------------------------------------------
factory/bench.py	Decision Record	keep	injected by tests; not a command-line option
factory/bench.py	Tautology	delete later	One Bench run records model sonnet and repeat 1. The Setup id, the
factory/bench.py	Tautology	delete later	harness command and the Review model are the arguments above.
factory/ci_gate.py	Decision Record	keep	CI conclusions that mean the run is over. `timed_out` and `skipped` are
factory/ci_gate.py	Decision Record	keep	over too: Rework must not sit out the whole wait for a comment that will
factory/ci_gate.py	Decision Record	keep	not be posted.
factory/ci_gate.py	Decision Record	keep	Token shapes the factory or a test might print. CI itself holds no secrets;
factory/ci_gate.py	Decision Record	keep	this is the belt on top of replacing values from the environment.
factory/ci_gate.py	Decision Record	keep	ignore | rework | human | join | settle | finish
factory/ci_gate.py	Decision Record	keep	"ticket" posts on the Ticket. "pull_request" posts on the pull request.
factory/ci_gate.py	Decision Record	keep	CI completes on pull_request. Review completes on pull_request_target.
factory/ci_gate.py	Decision Record	keep	Both are same-repo pull-request events; the workflow `if` admits both.
factory/ci_gate.py	Decision Record	keep	A green re-run of a head that already entered rework must not drop the
factory/ci_gate.py	Decision Record	keep	one-at-a-time lock while that round is still open.
factory/ci_gate.py	Decision Record	keep	Both spellings: `factory:in-progress` after sync, and `in-progress` until then.
factory/ci_gate.py	Decision Record	keep	Posted as the charge before the other comment was visible. Rewrite it
factory/ci_gate.py	Decision Record	keep	so it does not claim a round it did not take.
factory/claude.py	Decision Record	keep	Claude Code's model aliases, mapped to OpenRouter's model ids
factory/claude.py	Decision Record	keep	(https://openrouter.ai/docs/guides/coding-agents/claude-code-integration).
factory/claude.py	Decision Record	keep	Never passed to the agent, whatever the login.
factory/claude.py	Decision Record	keep	OpenRouter's guide: must be explicitly empty, or Claude Code uses it.
factory/claude.py	Decision Record	keep	The CLI's closing result message, or {}. It holds the model's text, so
factory/claude.py	Decision Record	keep	only `save_numbers` may write any of it to disk.
factory/claude.py	Decision Record	keep	Unattended: nobody is there to answer a permission prompt. The
factory/claude.py	Decision Record	keep	disallowed tools still bind, and the agent holds no GitHub token.
factory/claude.py	Decision Record	keep	The four counts, as the result line's `usage` names them and as its `modelUsage` does.
factory/collect_findings.py	Decision Record	keep	The workflow posts with its own GITHUB_TOKEN, so this is who wrote the marker comments.
factory/collect_findings.py	Decision Record	keep	kind, description, path, fix
factory/github.py	Decision Record	keep	Review runs on pull_request_target; CI runs on pull_request. A push to main
factory/github.py	Decision Record	keep	shares neither, so a run for this head from `push` is not the PR's check.
factory/github.py	Decision Record	keep	Issues and PRs share one number space; the issue endpoint takes both.
factory/github.py	Decision Record	keep	The factory's block in a PR body (written by `factory/ticket.py`, which Review never reads).
factory/github.py	Tautology	delete later	The Door (two-way or one-way) of a change: the vocabulary, the file the agent's claim goes
factory/github.py	Tautology	delete later	in, and how much of its reason is kept.
factory/github.py	Tautology	delete later	What a change that states no Door counts as.
factory/github.py	Tautology	delete later	What replaces a secret value in text the factory posts.
factory/github.py	Decision Record	keep	A zero-width space breaks the opener and closer without the entity, which a code span
factory/github.py	Decision Record	keep	would show as literal `&lt;`.
factory/metrics.py	Decision Record	keep	Historical start labels stay. `factory:start` is the name claim removes now.
factory/metrics.py	Decision Record	keep	`ready-for-factory` is not renamed; old timelines still count it.
factory/metrics.py	Decision Record	keep	The repo the committed fixtures were captured from, for the App slug when none is given.
factory/metrics.py	Tautology	delete later	---- reading ---------------------------------------------------------------------
factory/metrics.py	Tautology	delete later	---- grouping --------------------------------------------------------------------
factory/metrics.py	Tautology	delete later	---- the table -------------------------------------------------------------------
factory/metrics.py	Tautology	delete later	---- entry point -----------------------------------------------------------------
factory/picker.py	Decision Record	keep	A green settle already dropped the lock. The close still plans, so a
factory/picker.py	Decision Record	keep	Ticket this one blocked can start. Drop a lock only when this issue
factory/picker.py	Decision Record	keep	still wears one: that is the only close that needs the App token
factory/picker.py	Decision Record	keep	without also starting a Ticket.
factory/picker.py	Decision Record	keep	The closed Ticket is not an open candidate. Say why on it only when
factory/picker.py	Decision Record	keep	nothing starts and it still held the lock; a start comments on the
factory/picker.py	Decision Record	keep	Ticket that is starting.
factory/picker.py	Decision Record	keep	A refusal is posted with the workflow token. Adding factory:start waits
factory/picker.py	Decision Record	keep	for the App token in `apply`.
factory/record.py	Decision Record	keep	Every workflow a record may name. `WORKFLOWS` stays the three `factory.backfill` rebuilds
factory/record.py	Decision Record	keep	records for: the research path started after records did, so it has no past run to rebuild.
factory/record.py	Tautology	delete later	Anything that looks like a credential.
factory/record.py	Tautology	delete later	A credential, or anything that could open or close the HTML comment.
factory/record.py	Tautology	delete later	---- the marker ------------------------------------------------------------------
factory/record.py	Tautology	delete later	---- what the writers share ------------------------------------------------------
factory/record.py	Decision Record	keep	characters in one GitHub comment
factory/record.py	Decision Record	keep	GitHub would refuse it: the record stands alone
factory/research.py	Decision Record	keep	Review's read-only tools plus the web. Everything Review denies stays denied, the web aside:
factory/research.py	Decision Record	keep	no shell, no write tool, no helpers, and no /proc, where the agent's own login lives.
factory/research.py	Decision Record	keep	Not `factory.ticket.STARTED_PREFIX`: `factory.metrics` counts a comment with that prefix as a
factory/research.py	Decision Record	keep	build Ticket, and a Research request is not one.
factory/research.py	Tautology	delete later	---- the prompt ------------------------------------------------------------
factory/research.py	Tautology	delete later	---- steps -----------------------------------------------------------------
factory/research.py	Decision Record	keep	No `may_edit`: the agent gets no bypassPermissions, and no tool that writes.
factory/research.py	Decision Record	keep	Whatever ran before, this step never commits a note that fails.
factory/research.py	Decision Record	keep	The run is over: no Rework round follows, and the CI gate only releases `factory/` branches.
factory/research.py	Decision Record	keep	The problems are the checker's own words, but the file came from a job that ran the
factory/research.py	Decision Record	keep	agent: it must not form a hidden marker in the bot's comment.
factory/research_note.py	Excuse	fix later	The first two lines of this pattern are a verbatim copy of `factory.record.TOKEN_RE.pattern`. The
factory/research_note.py	Excuse	fix later	checker imports only the standard library, so it holds its own copy;
factory/research_note.py	Excuse	fix later	tests/factory/test_research_note.py checks the copy has not drifted.
factory/research_note.py	Tautology	delete later	text after "## ", stripped
factory/research_note.py	Tautology	delete later	the lines up to the next "## " heading (H3 and deeper stay in the body)
factory/research_note.py	Tautology	delete later	1-based line number of the heading in the text
factory/review_pr.py	Decision Record	keep	Before 2026-11-24 the factory put the issue label on a PR it had stopped; open PRs may still carry it.
factory/review_pr.py	Decision Record	keep	`factory-stopped` is the stop label from before this rename.
factory/review_pr.py	Decision Record	keep	The design's brake: stop after two rework rounds per ticket.
factory/review_pr.py	Decision Record	keep	Everything that could change a file, run a command or reach the network.
factory/review_pr.py	Decision Record	keep	The reviewer keeps Read, Grep and Glob. /proc is denied too: the agent's own
factory/review_pr.py	Decision Record	keep	environment holds the Claude login. A Read rule covers Grep and Glob as well.
factory/review_pr.py	Decision Record	keep	Second line of a factory comment. `charged=1` means this comment took the
factory/review_pr.py	Decision Record	keep	rework counter for that head; CI and Review share it, so a head is charged
factory/review_pr.py	Decision Record	keep	once. `add` is the labels that charge intended, so a re-run can finish them.
factory/review_pr.py	Tautology	delete later	GitHub's closing keywords, then #N or owner/repo#N.
factory/review_pr.py	Tautology	delete later	---- findings --------------------------------------------------------------
factory/review_pr.py	Tautology	delete later	---- pure decisions --------------------------------------------------------
factory/review_pr.py	Decision Record	keep	pass | rework | human | human-owned | stale | same-round | ci-blocked
factory/review_pr.py	Decision Record	keep	The summaries and findings are the model's text. Neutralised, they cannot form a
factory/review_pr.py	Decision Record	keep	hidden marker of the factory's (the review marker, the gate line, a Run record).
factory/review_pr.py	Tautology	delete later	---- the prompt ------------------------------------------------------------
factory/review_pr.py	Tautology	delete later	---- the three steps -------------------------------------------------------
factory/review_pr.py	Decision Record	keep	ValueError covers json.JSONDecodeError from a malformed `gh run list`.
factory/review_pr.py	Decision Record	keep	Written by the ci-conclusion step with GITHUB_TOKEN. Missing or empty
factory/review_pr.py	Decision Record	keep	means CI is unknown. Apply never lists workflow runs: the App token
factory/review_pr.py	Decision Record	keep	has no Actions permission.
factory/review_pr.py	Decision Record	keep	The last step of the job hands these to the `status` job (factory/review_status.py).
factory/review_pr.py	Decision Record	keep	The comment was posted as the charge. Another comment won, so this
factory/review_pr.py	Decision Record	keep	one must not keep claiming the round.
factory/review_pr.py	Decision Record	keep	Clearing in-progress is the CI gate's job. It checks the factory branch,
factory/review_pr.py	Decision Record	keep	the App author and that this head is not already in a rework round.
factory/review_pr.py	Decision Record	keep	A workflow command on stdout, so the run page shows it as an error.
factory/review_status.py	Decision Record	keep	A Verdict counts only once its comment is posted: report.md is written before the post.
factory/run_record.py	Decision Record	keep	The research run has its own check and leaves both fields null.
factory/run_record_review.py	Decision Record	keep	The sentence `render_report` writes under "Reviewed ..." for each outcome that moves
factory/run_record_review.py	Decision Record	keep	no labels. Tests run `apply` and this step together, so a change there shows here.
factory/sync_labels.py	Decision Record	keep	"create", "update", "rename", or "leave"
factory/sync_labels.py	Decision Record	keep	`edit` addresses the label by the name it already has on the repo.
factory/sync_labels.py	Decision Record	keep	A rename passes `--name` and does not also create the new name.
factory/ticket.py	Decision Record	keep	Readers accept the name from before the rename. Writers use the new one.
factory/ticket.py	Decision Record	keep	The agent may edit and run things in its checkout, but not reach the web or
factory/ticket.py	Decision Record	keep	spawn helpers, and not read /proc, where its own environment lives.
factory/ticket.py	Decision Record	keep	Lowercase words separated by single hyphens. This is what keeps a label suffix
factory/ticket.py	Decision Record	keep	inside projects/<name>/ when a workflow interpolates it into a path.
factory/ticket.py	Tautology	delete later	---- prompts ---------------------------------------------------------------
factory/ticket.py	Decision Record	keep	Both prompts. The work checkout is nested inside the factory's own checkout
factory/ticket.py	Decision Record	keep	(the default branch, where these scripts run). Publish commits only the work
factory/ticket.py	Decision Record	keep	checkout, so an edit in the outer one is thrown away.
factory/ticket.py	Decision Record	keep	Copied into the work checkout before the agent starts. The prompt names these
factory/ticket.py	Decision Record	keep	relative paths, never the absolute path of --out: --out lives in the factory
factory/ticket.py	Decision Record	keep	checkout, and an absolute path there is how an agent edits the wrong tree.
factory/ticket.py	Decision Record	keep	A Ticket with no `project:` label. The run is not a bootstrap, so verify runs
factory/ticket.py	Decision Record	keep	the Lab check, if there is one. The agent edits the factory itself.
factory/ticket.py	Decision Record	keep	Appended only when the check is not on the factory checkout yet. The paragraph
factory/ticket.py	Decision Record	keep	above still tells an existing Project to run its check; this one overrides that
factory/ticket.py	Decision Record	keep	for the Ticket that creates the check.
factory/ticket.py	Tautology	delete later	---- steps -----------------------------------------------------------------
factory/ticket.py	Decision Record	keep	the same limit as CI (.github/workflows/ci.yml)
factory/ticket.py	Decision Record	keep	Same credentials the agent step drops (factory/claude.py). The script was
factory/ticket.py	Decision Record	keep	just written or edited by the agent.
factory/ticket.py	Decision Record	keep	A deleted or de-executabled check shows in git status: it counts as touched.
factory/ticket.py	Decision Record	keep	Without rename detection a move lists both its old and its new path, so a file moved out of a
factory/ticket.py	Decision Record	keep	Project still counts for that Project's Blast Radius.
factory/ticket.py	Decision Record	keep	publish writes this; release includes it, with the agent's summary, in the
factory/ticket.py	Decision Record	keep	failure comment. The two steps are separate processes and share only --out.
factory/ticket.py	Decision Record	keep	The start of the comments publish and release post. `factory.run_record` finds
factory/ticket.py	Decision Record	keep	the run's comment by these, so a file in --out never picks which comment is edited.
factory/ticket.py	Decision Record	keep	A new Ticket's branch must not exist yet; a rework round fast-forwards.
factory/ticket.py	Decision Record	keep	A Rework push stages only this round's edits, so the Blast Radius reads the whole PR.
factory/ticket.py	Decision Record	keep	The file holds paths from the checkout and the summary is the agent's own text:
factory/ticket.py	Decision Record	keep	neither may form a hidden marker in the bot's comment.
projects/harness/src/harness_lab/loop.py	Decision Record	keep	projects/harness/runs/
projects/harness/src/harness_lab/loop.py	Decision Record	keep	Cost only when OpenRouter reports it; never estimated.
projects/harness/src/harness_lab/standin.py	Decision Record	keep	each: {"path", "headers", "body"}
projects/harness/src/harness_lab/tools.py	Decision Record	keep	projects/harness/workspace/, the only folder the tools may read.
projects/harness/src/harness_lab/tools.py	Tautology	delete later	The tool definition, in Anthropic's tool format.
projects/harness/src/harness_lab/tools.py	Decision Record	keep	"ok", "error" (failed) or "refused" (outside the workspace)
tests/experiments/test_experiment.py	Tautology	delete later	--- check 1: format ---------------------------------------------------------------
tests/experiments/test_experiment.py	Tautology	delete later	--- check 2: ceilings and secrets --------------------------------------------------
tests/experiments/test_experiment.py	Decision Record	keep	A bad source line is normally quoted in its error; with a token in it, it is not.
tests/experiments/test_experiment.py	Tautology	delete later	--- check 3: runner ----------------------------------------------------------------
tests/experiments/test_experiment.py	Tautology	delete later	--- check 4: stdlib only -----------------------------------------------------------
tests/factory/support.py	Decision Record	keep	A string shaped like a credential, built here so no file holds one.
tests/factory/test_backfill.py	Decision Record	keep	Text a transcript holds and a record must never hold.
tests/factory/test_backfill.py	Decision Record	keep	the listing shows the latest attempt only
tests/factory/test_backfill.py	Tautology	delete later	---- what the jobs, the comments and the clock establish (code review B5) -----------------
tests/factory/test_bench.py	Tautology	delete later	no injected agent, and no recorded answer to replay
tests/factory/test_bench.py	Tautology	delete later	a failed case still exits 0
tests/factory/test_bench.py	Decision Record	keep	0.5 spent of 3.5 leaves 3.0: still enough; then 1.0 spent leaves 2.5: refused
tests/factory/test_bench.py	Tautology	delete later	---- replay ----------------------------------------------------------------
tests/factory/test_bench.py	Tautology	delete later	---- planted-defect cases --------------------------------------------------
tests/factory/test_ci_context.py	Decision Record	keep	one entry per poll; an Exception is raised
tests/factory/test_ci_context.py	Decision Record	keep	t = 0, 15, 30, 45, 60
tests/factory/test_ci_projects.py	Decision Record	keep	A deleted project, or a stray file directly under projects/, checks nothing.
tests/factory/test_ci_projects.py	Decision Record	keep	no check: not a Project yet
tests/factory/test_collect_findings.py	Tautology	delete later	---- review_for_head ------------------------------------------------------
tests/factory/test_collect_findings.py	Tautology	delete later	---- standards_findings ----------------------------------------------------
tests/factory/test_collect_findings.py	Tautology	delete later	---- hostile text ------------------------------------------------------------
tests/factory/test_collect_findings.py	Tautology	delete later	only our own header marker
tests/factory/test_collect_findings.py	Tautology	delete later	---- collect: once, nothing, rolling issue ---------------------------------
tests/factory/test_collect_findings.py	Decision Record	keep	a second PR's number reads another thread
tests/factory/test_collect_findings.py	Tautology	delete later	---- the workflow text -------------------------------------------------------
tests/factory/test_metrics.py	Tautology	delete later	---- labels, pull requests, CI and git (ticket 146) --------------------------------
tests/factory/test_metrics.py	Tautology	delete later	---- which Tickets count: the bot claimed them, or a record names them ------------
tests/factory/test_override.py	Decision Record	keep	The fake PR knows only its state and head sha, and has no Review comment: a fork PR.
tests/factory/test_research.py	Decision Record	keep	Built at test time so no file holds a credential-shaped literal.
tests/factory/test_research.py	Tautology	delete later	---- the tools -------------------------------------------------------------
tests/factory/test_research.py	Tautology	delete later	---- the request -----------------------------------------------------------
tests/factory/test_research.py	Tautology	delete later	A comment alone is empty too.
tests/factory/test_research.py	Tautology	delete later	---- claim -----------------------------------------------------------------
tests/factory/test_research.py	Tautology	delete later	---- answer ----------------------------------------------------------------
tests/factory/test_research.py	Tautology	delete later	---- note_from_reply and compose ---------------------------------------------
tests/factory/test_research.py	Tautology	delete later	---- check -----------------------------------------------------------------
tests/factory/test_research.py	Tautology	delete later	---- publish ---------------------------------------------------------------
tests/factory/test_research.py	Tautology	delete later	---- release ---------------------------------------------------------------
tests/factory/test_research.py	Tautology	delete later	---- the Run record ----------------------------------------------------------
tests/factory/test_research.py	Tautology	delete later	---- the workflow ------------------------------------------------------------
tests/factory/test_research_note.py	Decision Record	keep	Built here so no file holds a credential-shaped string.
tests/factory/test_review_cap.py	Decision Record	keep	This run itself is never counted, and a run from before 00:00 UTC today is not today's.
tests/factory/test_review_door.py	Decision Record	keep	the PR above has no closing keyword, so the body is the requirement
tests/factory/test_review_status.py	Decision Record	keep	The post failed: report.md was written but comment-id.txt and outcome.txt were not.
tests/factory/test_run_record.py	Tautology	delete later	---- the last step ------------------------------------------------------------
tests/factory/test_run_record.py	Tautology	delete later	raises MetricsError on a refused record
tests/factory/test_run_record.py	Tautology	delete later	---- the last step trusts nothing the agent step wrote ------------------------------
tests/factory/test_run_record.py	Tautology	delete later	---- a wrong-typed `usage` is null, not replaced by `model_usage` (code review A4) ----
tests/factory/test_run_record.py	Tautology	delete later	---- a marker in model text is not a record (code review A1) ------------------------
tests/factory/test_run_record_review.py	Decision Record	keep	The report is posted by the bot; the fake attributes every comment to it.
tests/factory/test_run_record_review.py	Tautology	delete later	---- the project comes from the linked Ticket's label (code review B3) ------------------
tests/factory/test_run_record_review.py	Tautology	delete later	both runs
tests/factory/test_run_record_review.py	Decision Record	keep	apply ran earlier with the real context; the last step must not read it again.
tests/factory/test_run_record_review.py	Tautology	delete later	---- a marker in model text is not a record (code review A1) ---------------------------
tests/factory/test_run_record_review.py	Tautology	delete later	one draft, first pass BLOCKED
tests/factory/test_ticket.py	Tautology	delete later	commits the check as the base
tests/factory/test_ticket_parser.py	Decision Record	keep	the workflow passes no --root: the default "."
tests/factory/test_ticket_parser.py	Decision Record	keep	the workflow passes no --root: the default "."
tests/factory/test_ticket_parser.py	Decision Record	keep	`_args` builds its base with a dict literal; call sites override with keywords.
tests/factory/test_workflow_skill.py	Tautology	delete later	skip header and rule
```
