# Review calibration against the owner, 2026-11-15

How often the factory's Review (the LLM judge in `factory/review_pr.py`) reached the same call as the owner on the 11 Tickets the factory has built, measured from records that already exist. Nothing was re-run: no model call, no code change, no GitHub write.

**11 Tickets is a small sample.** One Ticket moves any rate here by 9 points, and a 95% interval around the headline 6 of 11 runs from about 28% to 79%. Read the counts as a list of cases to look at, not as rates to track.

## Summary

- **Agreement: 6 of 11 Tickets** (#7, #8, #9, #10, #17, #115).
- **Misses: 4 of 11** (#18, #114, #116, #128). The Review said PASS and the owner later fixed something real. Only one of the four (#18) broke a sentence the Ticket states and could be seen by reading the diff.
- **False blocks: 1 of 11** (#127). The owner merged with the Review still BLOCKED on the merged commit.
- **No Ticket was reverted.**
- At the level of single findings the picture reverses. Of the 14 blocking findings where the owner's own hand shows what they thought, the owner acted on 7 and did not act on 7.
- PR #151's `open_question` kind would probably have turned the final verdict on #9 and #17 from BLOCKED to PASS (inferred). Those are the two Tickets where the owner fixed by hand what the Review blocked on. It would not have changed any of the four misses.

So on this sample the Review's verdict errs lenient more often than strict, its individual findings err strict, and #151 moves it further toward lenient. That is the case for the planted-defect Bench cases at the end.

## Method

**Sources.** `factory/run-records-backfill.jsonl`, `uv run python -m factory.metrics --repo travism26/harness-lab --backfill factory/run-records-backfill.jsonl`, the Review comments on each PR, each PR's commits and timeline, and `git log` on `main` after each merge.

**Unit.** One row per Ticket. The Review's verdict for a Ticket is the last verdict it posted before the merge. The owner outcome is the label:

| Label | Review's last verdict | Owner outcome |
|---|---|---|
| Agree (PASS) | PASS | Merged with no owner fix, and nothing in it fixed since |
| Agree (BLOCKED) | BLOCKED | Owner fixed by hand something a blocking finding named, then merged |
| False block | BLOCKED | Owner merged without fixing what the blocking findings named |
| Miss | PASS | Owner fixed something real in the Ticket's code, before or after the merge |

**How the Review decides.** The model does not state a verdict. Code derives it: BLOCKED when any Spec finding is `missing_requirement` or `implemented_wrongly`, PASS otherwise. `scope_creep` and every Standards finding are notes. The Review reads the Ticket's title and body, the diff and the code; it runs nothing and does not see earlier Reviews of the same PR.

**Counts behind the table.** The Run records hold 37 Review runs for these 11 Tickets. Two failed. Seven ran after the merge and posted nothing. That leaves 28 posted Reviews: 17 BLOCKED and 11 PASS, all from `claude-sonnet-5-5`.

## Per-Ticket table

Verdicts are in posting order, one per reviewed commit. "Owner commits" counts only commits that changed behaviour; the metrics report counts 10 because it includes two empty retrigger commits and a merge of `main` on #130.

| Ticket | PR | Review verdicts | Verdict at merge | Owner commits | What the owner fixed | Label |
|---|---|---|---|---|---|---|
| #7 | #11 | PASS | PASS | 0 | Nothing | Agree (PASS) |
| #8 | #23 | PASS | PASS | 0 | Nothing | Agree (PASS) |
| #9 | #24 | BLOCKED, BLOCKED, BLOCKED | BLOCKED | 2 | Turn cap below 1 rejected; unresolvable path made an error (`d1b8a68`). `--model` flag restored (`39a1e39`) | Agree (BLOCKED), with one miss inside it |
| #10 | #25 | BLOCKED, BLOCKED, PASS | PASS | 0 | Nothing | Agree (PASS) |
| #17 | #20 | BLOCKED, PASS, BLOCKED, BLOCKED | BLOCKED | 2 | One comment path (`d1d8c5e`). Harness made a uv workspace member (`cd26251`) | Agree (BLOCKED) |
| #18 | #26 | BLOCKED, PASS | PASS | 0 | Four days later: a rework refusal crashed before it could comment (`a4368e5`, PR #112) | Miss |
| #114 | #118 | PASS, PASS, PASS | PASS | 1 | Before merge: shutdown hung when a client sent no request, which failed CI (`43ae7f5`) | Miss |
| #115 | #125 | BLOCKED, BLOCKED, PASS | PASS | 0 | Nothing found | Agree (PASS) |
| #116 | #135 | PASS | PASS | 0 | Not fixed yet: a live run recorded 0 tokens on every streamed call (#138, #147) | Miss |
| #127 | #130 | BLOCKED ×5 | BLOCKED | 2 | Unread lock field dropped (`800d182`). Owner command made able to write a ledger line (`2019b40`). Merged over the fifth BLOCKED | False block |
| #128 | #133 | BLOCKED, PASS | PASS | 0 | Two days later: the Bench's build prompt named a Ticket file that was already deleted (`923a3b1`, PR #151) | Miss |

## Findings

### 1. Agreement: 6 of 11

- **PASS, merged as built, nothing fixed since (4):** #7, #8, #10, #115.
- **BLOCKED, owner fixed what was named (2):** #9 and #17.

Split by verdict: of the 8 Tickets merged on a PASS, 4 were clean and 4 were misses. Of the 3 merged on a BLOCKED, the owner agreed with 2.

#7 is the weakest of the six. The Ticket says "Model choice: `--model`, else `HARNESS_MODEL`, else Haiku 5.5". PR #11 delivered the choice as a function and said in its description that it had not wired a `--model` flag, since no command existed yet. The Review passed it and the owner merged it as built, so it counts as agreement. The flag then went missing in #9 (see the end of finding 2).

### 2. Misses: 4 of 11

| Ticket | Defect | Breaks a stated Ticket sentence? | Could reading the diff have caught it? |
|---|---|---|---|
| #18 | `revise` used `args.run_url`, but the `revise` parser had no `--run-url`, so a real refusal raised before commenting | Yes: "the factory comments why on the ticket", for "building or reworking" | Yes. The handler and the parser are both in `factory/ticket.py`. The tests built the arguments by hand, which hid it |
| #114 | Shutdown waited out its own five-second deadline on an idle connection | No | Unlikely (inferred). CI caught it on the first push; the Review does not run code |
| #116 | Usage parsing read a compressed stream as if it were plain text | No. The Ticket never mentions content encoding | Only by tracing the forwarded `Accept-Encoding` against `DisableCompression: true`. Found by a live run |
| #128 | The prompt was built inside a temporary directory that was gone before `claude` started; 12 of 12 live builds produced nothing | No. The Ticket calls the live run an owner step | Readable, but the Ticket's tests never start `claude`. The Review did flag that code, as `scope_creep` |

Only #18 is the Review getting its own job wrong: a stated sentence, broken, in plain sight. It is also the only miss in code that a rework round wrote in answer to the Review's own blocking finding; the next Review passed the fix without checking that it could run.

The other three are defects outside what a read-only judge of the Ticket text is set up to see. They are misses of the Review by the definition used here, and they are also a measure of how much the factory leans on CI and live runs. If only #18 counts as a miss, agreement is 9 of 11.

**One more miss sits inside #9 and is not in the count.** The second rework round removed the `--model` flag after the Review called it scope creep. The third Review did not notice it was gone. The owner put it back and wrote on PR #24: "The review missed this: spec #6 story 15 and #7 ask for `--model`". Ticket #9's own body never mentions `--model`, so the Review's input did not contain the requirement.

### 3. False blocks: 1 of 11

**#127.** The fifth Review blocked the merged commit on one `missing_requirement`: the run does not hold a reservation, and the Setup carries no build prompt. The owner changed neither and merged four hours later. The same reservation point had been a blocking finding in four of the five Reviews.

The earlier rounds on #127 were not all false. The owner did drop the unread `reservation_usd` field, an option the first Review offered, and did fix the fourth Review's finding that the documented command could not write a ledger line.

### 4. Single findings are stricter than the verdicts suggest

The 17 BLOCKED Reviews carry 28 blocking findings.

| What happened to the finding | Count | Tickets |
|---|---|---|
| A rework round changed the code and the owner merged the result | 14 | #10 (3), #17 (3), #18 (2), #115 (5), #127 (1) |
| The owner fixed it by hand | 7 | #9 turn cap (2), #17 unused `pyproject.toml` (1), #127 unread lock field (3), #127 command cannot write a line (1) |
| The owner left it standing or did the opposite | 7 | #9 (3), #115 (1), #127 (2), #128 (1) |

The first row says nothing about agreement: the owner merged reworked code and never saw the alternative. In the other two rows the owner's view shows, and it splits 7 to 7.

The seven the owner did not act on:

- **#9:** an unresolvable path should count as refused (the owner made it an ordinary error, the opposite); no reply event is logged for a failed Turn; the tests do not check Run log field values. The last two are still true of the merged code (inferred; the owner's commits did not touch them).
- **#115:** the transport adds `Content-Length: 0`. The finding's own fix line said to leave it as it is.
- **#127:** the model and repeat are hardcoded; the reservation is never held.
- **#128:** the committed Ticket text might not match its hash. The Review wrote "I couldn't confirm". The hashes did match.

### 5. Later rounds contradict earlier ones

Four of the seven Tickets that were ever BLOCKED show a later Review reversing an earlier one:

- **#9:** round 2 called the turn-cap validation and `--model` scope creep, and the rework removed them. Round 3 blocked on the missing validation.
- **#17:** round 1 required doc rewording; rounds 3 and 4 called that rewording scope creep. The Review passed commit `f2a796b`, then blocked the next commit, which differed by one comment line, on files that had not changed. The unused harness `pyproject.toml` it blocked on in round 4 was already there when it passed. The owner opened #22 about this.
- **#115:** round 2 blocked because an unreadable request body wrote no Call record. The rework added a 400 path. Round 3 called the 400 path scope creep.
- **#127:** round 2 called the `--model` and `--repeat` options scope creep, and the rework removed them. Round 3 blocked because the model and repeat were hardcoded.

Two mechanisms are visible. Each Review starts without the earlier Reviews. And the rework agent acts on notes as well as blockers, so a non-blocking `scope_creep` note can delete code that the next Review, or the owner, wants back.

### 6. The owner's hand fixes were never reviewed

On #9 and #17 the PR carried `ready-for-human` when the owner pushed, and the Review skips PRs with that label. The owner then marked each PR ready and merged within seconds. So there is no Review verdict on any commit the owner wrote for those two Tickets.

## What PR #151 would have changed

PR #151 added the non-blocking Spec kind `open_question` and narrowed the two blocking kinds to a finding that quotes a Ticket sentence, names the place in the diff that breaks it, and states the breach as a fact.

Everything in this section is **inferred** from reading each old finding against the new wording. The one measured point is the turn-cap finding: #151's own Bench replay of Ticket 9 went from 0 of 3 passed to 3 of 3, on newly built diffs, not on the diff from PR #24.

| Ticket | Review | Blocking finding | Under #151 (inferred) | Effect |
|---|---|---|---|---|
| #9 | 1st, 3rd | `--max-turns 0` not rejected. Ticket says only "Turn cap is a setting, default 10" | `open_question` (measured on the Bench) | 3rd Review becomes PASS |
| #9 | 1st | Unresolvable path not counted as refused. Ticket silent | `open_question` | With the row above, the 1st Review becomes PASS and no rework round runs |
| #10 | 2nd | A table cell says "Rework rounds: 1 (this round)". Ticket silent on the table | `open_question`, less sure | PASS one round earlier |
| #17 | 3rd | `check` does not use the locked environment. Ticket silent | `open_question` | PASS |
| #17 | 4th | Harness `pyproject.toml` is unused. The quoted sentence only says the file lives there, and it does | `open_question` | PASS |
| #115 | 2nd | No Call record for an unreadable body (fix: "Decide whether") and `Content-Length: 0` (fix: "Leave this as is") | Both match the new wording almost word for word | PASS one round earlier; the 400 path is never added |
| #128 | 1st | Ticket text might not match its hash: "I couldn't confirm" | `open_question` ("anything you could not confirm by reading") | PASS with no rework round |
| #127 | 3rd | Hardcoded model and repeat. Ticket silent on options | `open_question` | No change; the reservation finding still blocks that round |
| #127 | 1st, 2nd, 3rd, 5th | Reservation not held. Quotes two Ticket sentences that read two ways | Could not tell | Could not tell |

Unchanged: #10 first Review, #17 first Review, #18, #115 first Review, #127 fourth Review. Each quotes a Ticket sentence the diff plainly broke.

What follows from the table, all inferred:

- **Rework rounds.** Up to 6 of the 12 rounds would not have run: #9 (2), #10 (1), #17 (1), #115 (1), #128 (1).
- **Final verdicts.** #9 and #17 flip from BLOCKED to PASS. In both, the owner fixed by hand the thing that would now be a note: a turn cap below 1, and the unused `pyproject.toml`. Under the labels above they would move from agreement to miss, unless the owner reads the note and acts on it at merge, which is what #151's own description says is intended.
- **Why this happens.** Of the four distinct issues the owner fixed by hand after a block, three were the Review's own inference past what the Ticket states (the turn cap, the unused `pyproject.toml`, the unread lock field) and the fourth quotes a sentence that reads two ways. The blocks the owner valued most were not Ticket breaches.
- **The false block.** Could not tell whether #127's fifth Review would still block.
- **The misses.** No change. All four were already PASS.
- **One side effect.** On #9 the build commit already had `--model`. With a PASS on the first Review there is no second round to remove it, so the owner's second commit would not have been needed.

## Three proposed planted-defect Bench cases

**Built since** (Goal [#194](https://github.com/travism26/harness-lab/issues/194)): the three cases and their twins are `factory/bench_cases/planted-8.json`, `factory/bench_cases/planted-9.json` and `factory/bench_cases/planted-18.json`, each with a `-twin` file. `factory/bench.py` applies the patch and scores the run, and `docs/factory/README.md` ("Planted-defect Bench cases") gives the pass rule and the two commands. Case 3's open point is settled: its check command is `uv run --locked pytest tests/factory`. No live run has been made yet. The rest of this section is the proposal as written on 2026-11-15.

Not built. Each is a past Ticket plus a patch that contains a breach of a sentence the Ticket states outright, with the check still green, so the Review is the only thing between the breach and a pass.

**What they need that the Bench does not have** (`factory/bench.py`): a Bench case cannot supply a ready-made diff, and a Bench run passes only when the check passes and the Review says PASS. A planted case needs a patch applied in place of the build step, and an expected verdict of BLOCKED. The glossary defines a Bench case as "one past Ticket", so the term would need a line too.

**Pass/fail check, the same for all three.** A Bench run passes when all of these hold:

1. The check passes. If it fails, the patch is wrong and the run tells you nothing about the Review.
2. The Review's verdict is BLOCKED.
3. At least one blocking finding names the planted file. This guards against a BLOCKED for an unrelated reason, which finding 4 shows is common.

The case passes at 3 of 3 repeats. Each case also needs a twin with the same patch minus the planted change, expected PASS; without the twin, a Review that blocks everything passes all three.

### Case 1: symlink escape not refused (Ticket #8, Project `harness`)

- **Stated sentences:** "Any path that resolves outside it (including `..` and symlink escapes) is refused with a tool result saying so." and "Acceptance: tests show a successful read, a missing file, a `..` escape refused and a symlink escape refused."
- **Start commit:** `0cad2cd`, the one `factory/bench_cases/ticket-8.json` already uses.
- **Patch:** the diff PR #23 merged, with two changes. `read_file` in `projects/harness/src/harness_lab/tools.py` checks the joined path without resolving it, so `..` is still refused but a symlink inside the workspace that points outside is read. `test_symlink_escape_refused` is removed.
- **Planted file:** `projects/harness/src/harness_lab/tools.py` or `projects/harness/tests/test_tools.py`.
- **What it tests:** the easiest level. One stated behaviour is missing and one stated test is missing. A Review that passes this is not checking criteria one by one.

### Case 2: turn cap exits 0 (Ticket #9, Project `harness`)

- **Stated sentence:** "prints the final answer and exits non-zero on missing key, provider error or turn cap."
- **Start commit:** `7a0d2be`, the one `factory/bench_cases/ticket-9.json` already uses.
- **Patch:** the diff PR #24 merged, with two changes. `main` in `projects/harness/src/harness_lab/cli.py` returns 0 when the Run stops at the turn cap. `test_turn_cap` and `test_turn_cap_from_env` keep their Run log assertions and lose the exit-code assertion.
- **Planted file:** `projects/harness/src/harness_lab/cli.py`.
- **What it tests:** a requirement that is implemented, but wrongly, with tests that look complete. It is also the direct counterpart to #151, which stopped blocking on a turn-cap point the Ticket is silent on (a cap of 0). This case checks that the new wording still blocks a turn-cap breach the Ticket does state.

### Case 3: rework refusal crashes before it comments (Ticket #18, factory root)

- **Stated sentence:** on a refusal "the factory comments why on the ticket", and the factory reads the label "when building or reworking".
- **Start commit:** `089fdbc`, the base of PR #26.
- **Patch:** the diff PR #26 merged, unchanged. The defect is real: `revise` reads `args.run_url`, and the `revise` parser defines no `--run-url`.
- **Planted file:** `factory/ticket.py`.
- **What it tests:** the one miss in this sample that broke a stated sentence. The Review passed this exact diff on 2026-11-07, so the case starts with a known baseline of 0 of 1. It is the hardest of the three, because the breach shows only when the handler is read against the parser. A failure here says the Review reads too shallowly, more than that it is lenient.
- **Open point:** the check command for factory-root code at `089fdbc` needs confirming. Both existing Bench cases use `projects/harness/check`.

## Switching rule and runs

Written on 2026-11-25, before any run, so the result cannot shape the rule. The Bench's Review can now run on another model (`--review-model`, `docs/factory/README.md`, "The Bench's review model"). Live Review stays on sonnet until the rule below says otherwise.

**The rule.** Live Review switches to opus only if opus catches at least one planted case that sonnet misses, in 3 of 3 repeats, with no extra false block on the twins. Anything short stays on sonnet.

- **Catches, in 3 of 3 repeats:** the planted case's line in the opus report says `passed 3 of 3`. Each of the three Bench runs was BLOCKED and named a planted file.
- **Sonnet misses:** the same case's line in the sonnet report says fewer than 3 of 3.
- **No extra false block:** a false block is a twin's Bench run that ends BLOCKED. On each of the three twins, opus has no more of them than sonnet.
- **Review errors:** a Review that ends in `error` says nothing about the model, and a Review stopped by the review cap is one. A case with a Review error in either column does not count toward a switch.

A tie stays on sonnet, and so does opus doing better on a case by less than 3 of 3.

**The owner commands,** on the metered key, one after the other:

1. `uv run python -m factory.bench --replay-planted --review-model sonnet`
2. `uv run python -m factory.bench --replay-planted --review-model opus`

Each makes 18 Bench runs and reserves $1 for each, so the two together spend at most about $36 of the month's cap. Both write to the same ledger; the rows differ in `review_model`, and in `setup_id` (`claude-code-sonnet` and `claude-code-sonnet-review-opus`). Each cell below comes from that command's report: `passed N of 3` and `Review errors N` on the case's line.

**Results.** Empty until the owner has run both commands.

| Case | sonnet: passed of 3 | opus: passed of 3 | sonnet: Review errors | opus: Review errors |
|---|---|---|---|---|
| `planted-8` | | | | |
| `planted-8-twin` | | | | |
| `planted-9` | | | | |
| `planted-9-twin` | | | | |
| `planted-18` | | | | |
| `planted-18-twin` | | | | |

**What a switch is.** The owner sets the repository variable `FACTORY_REVIEW_MODEL` to `opus`. No file in this repo changes, and the Bench's own default stays sonnet.

## What I could not tell

- **Whether the owner would have merged the code before a rework.** For 14 of the 28 blocking findings the owner only ever saw the reworked version. Those findings carry no agreement signal in either direction.
- **Why the owner merged #130 over a BLOCKED.** There is no comment on the PR or the Ticket; the only explanation is in the commit messages.
- **Whether the label is finished.** "Nothing fixed since" can still become a miss. The oldest Ticket here merged 8 days ago and the newest 2. #116's defect is confirmed and has no fix on `main` yet.
- **Whether #115 shares #116's defect.** `DisableCompression: true` was already in the code #115 merged, so a compressed non-stream reply may also record 0 tokens (inferred). The live run had only streamed calls.
- **Whether #114's shutdown hang was a real defect or a fragile test.** The owner's commit message says real. The commit also removed the test that failed. Its author is a Cursor agent with the owner as co-author; the same is true of the #130 commits and `a4368e5`.
- **Whether three of #9's blocking findings still hold in the merged code.** I did not read the final `loop.py` and `test_cli.py` for the failed-Turn events or the log-field tests.
- **Anything about #151 beyond the turn-cap finding.** The rest of that section is my reading of old findings against new wording. Checking it means re-running the Review, which this task ruled out.
- **Review runs that failed.** Two failed runs on #130 (one with an answer that did not parse) and one earlier failure with no Run record are left out.
- **Whether this generalises.** One owner, one review model, merges across seven days, three Projects and the factory root. About 33 other PRs have Review records but are not among the 11 Tickets the metrics report counts; they are outside this count and would be the cheapest way to enlarge the sample.
