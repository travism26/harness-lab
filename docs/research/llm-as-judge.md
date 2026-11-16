# LLM-as-judge for the factory

Research note, checked 2026-11-15. It asks whether the factory should add an LLM judge, and how. Nothing here is a decision.

In this repo the judge already exists: it is the Review (`factory/review_pr.py`). "Judge" below means any model that grades another model's work; "the Review" means ours.

## Summary

- **Policy.** Anthropic's docs describe a subscription token as a supported login for unattended CI: "For CI pipelines, scripts, or other environments where interactive browser login isn't available, generate a one-year OAuth token with `claude setup-token`". API keys are not required. The Consumer Terms (effective Oct 8, 2025) bar automated access unless Anthropic "otherwise explicitly permit[s] it", and no Anthropic page says the docs are that permission. The docs do rule out using a subscription login for a product or for other people's usage, which is what the switch rule in `docs/adr/0003-factory-claude-code-on-subscription-token-with-switch-rule.md` already guards.
- **What practitioners do.** Judges that ship are pointwise, binary and narrow: one pass/fail question per criterion, no 1–5 scales. Teams use tests for correctness and a judge for what tests cannot see. Pairwise judging appears mainly in research and in choosing between candidate patches.
- **Zach Lloyd / Warp.** Warp scores recorded agent runs offline with model-based evaluators, each looking for one thing (for example a redundant test). The scores on their benchmark chart "came from an LLM judge", and human grading had not yet been added. I found no Warp statement on rubric design or judge calibration.
- **Failure modes that apply to a single-PR PASS/BLOCKED judge.** False PASS on plausible code, false BLOCKED on correct code, sway from text the author wrote, and same-family bias. Position bias is a pairwise problem and mostly does not apply.
- **Mitigations with evidence.** Giving the judge execution results has the most consistent support for code. A stronger or different reviewer helps only if it is stronger than the writer. Panels reduce same-family bias without removing it. Asking for explanations and fixes made false rejections worse in one code study.
- **Calibration.** The working method is: label real cases pass/fail by hand, report the judge's true-positive and true-negative rates separately, tune on one split and score once on a held-out split. Published code-judge validations used 100 to 115 labelled items.
- **What our sample size can show.** With 30 to 100 labels, an observed 90% has a 95% interval about 12 to 22 points wide. That is enough to catch a judge that is badly wrong, and not enough to compare two prompts a few points apart.
- **Cost.** Our Review costs a mean of $0.124 per Factory run and about $0.26 per PR (client estimates, 91 Reviews). Published per-review prices for agentic reviewers run from about $0.25 to $10 average (GitHub Copilot's own estimates). No one publishes a measured per-PR cost for a diff-plus-ticket PASS/BLOCKED judge.
- **For harness-lab.** The Review has never been measured: there are no human labels and no planted-defect cases. The cheapest useful step is to measure it. The best-supported change is to show it the check results. A second judge is the most expensive option and has the weakest support for our setup.

### How to read this note

Each claim carries a link and one of these labels:

- **[vendor]**: a company describing its own product, prices or results.
- **[independent]**: a paper or preprint by authors who are not selling the thing measured.
- **[practitioner]**: advice from someone experienced, without data.
- **[own arithmetic]**: computed for this note from linked figures.
- **[repo]**: read from this repo at commit `1de149d`.

Papers were read at their arXiv abstract page unless marked "full text". Anthropic pages carry no date unless stated, so their date is the fetch date, 2026-11-15. Figures that appeared only in search-result snippets are left out.

## 1. Policy: subscription login or API key in unattended GitHub Actions

**Answer.** Anthropic documents the subscription token as a supported login for CI and for the Claude Code GitHub Action. API keys are one option, not a requirement. The permission lives in product docs, not in the terms of service, and it covers your own usage only.

### What the terms say

[Consumer Terms of Service](https://www.anthropic.com/legal/consumer-terms), effective Oct 8, 2025, section 3, list item 7 **[vendor]**. The list opens "You may not access or use, or help another person to access or use, our Services in the following ways:". Item 7 begins:

> Except when you are accessing our Services via an Anthropic API Key or where we otherwise explicitly permit it,

and goes on to bar access "through automated or non-human means", naming bots and scripts as examples. (I confirmed these fragments on the page; the fetch tool would not return the item as one unbroken quote.)

The same page says the [Commercial Terms](https://www.anthropic.com/legal/commercial-terms) "govern your use of any Anthropic API key".

### What the docs say

All **[vendor]**, undated, fetched 2026-11-15.

[Authentication](https://code.claude.com/docs/en/authentication), "Generate a long-lived token":

> For CI pipelines, scripts, or other environments where interactive browser login isn't available, generate a one-year OAuth token with `claude setup-token`

> This token authenticates with your Claude subscription and requires a Pro, Max, Ultra, Team, or Enterprise plan.

[Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions), "Manage costs":

> If you authenticate with an OAuth token, runs use your Claude subscription instead of API billing.

The same page lists `CLAUDE_CODE_OAUTH_TOKEN` as one of two secrets to add, and says of its examples, which include a cron-scheduled run: "If you authenticate with a Claude subscription, replace the `anthropic_api_key` line in any example". For a secret shared across repositories it says to use an API key, "since an OAuth token is tied to the subscription of the person who ran `claude setup-token`".

[Legal and compliance](https://code.claude.com/docs/en/legal-and-compliance), "Authentication and credential use":

> **OAuth authentication** is intended exclusively for purchasers of Claude Free, Pro, Max, Ultra, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications.

> **Developers** building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider. Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users.

> Advertised usage limits for Pro, Max, and Ultra plans assume ordinary, individual usage of Claude Code and the Agent SDK.

It also says the restriction does not "prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription", and that Anthropic "reserves the right to take measures to enforce these restrictions and may do so without prior notice".

### How CI usage is billed

- On a plan login, "the Claude Agent SDK and `claude -p` still draw from your subscription limits" ([Help Center](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan), note dated October 7, 2026). A note dated June 15, 2026 on the same page says "We've paused the previously-announced changes to Claude Agent SDK usage." **[vendor]**
- Max, Ultra and Team plans include monthly API credits ($100 on Max, $200 on Ultra). They cover `claude -p` and the Agent SDK only when run with an API key from the linked Console organization. "Runs started by the Claude Code GitHub Action, an IDE extension or the Claude desktop app count as Claude Code usage", so the credits do not cover them ([Help Center](https://support.claude.com/en/articles/17154008-monthly-api-credits-for-max-ultra-and-team-plans), shown as "Updated over 2 weeks ago"). **[vendor]**

### Claude Code in CI specifically

- The factory does not use `anthropics/claude-code-action`. Each workflow installs the CLI pinned to 2.1.319 and runs `claude -p` with `CLAUDE_CODE_OAUTH_TOKEN` (`.github/workflows/review.yml`, `factory/claude.py`). The Authentication page's "CI pipelines, scripts" sentence covers that path. **[repo]**
- A risk to that path: "`--bare` is the recommended mode for scripted and SDK calls, and will become the default for `-p` in a future release", and "bare mode doesn't use your subscription login" ([Run Claude Code programmatically](https://code.claude.com/docs/en/headless)). The Authentication page adds "Bare mode does not read `CLAUDE_CODE_OAUTH_TOKEN`." No date is given for the change. **[vendor]**

### What this does and does not settle

- It settles that a subscription token in Actions is a setup Anthropic documents and offers during `/install-github-app`.
- It does not settle whether those docs are the "otherwise explicitly permit" exception in the Consumer Terms. That is my reading; no Anthropic page states it. The Legal page points to sales for "questions about permitted authentication methods for your use case".
- "Ordinary, individual usage" is not defined. A factory that runs many unattended Factory runs could be argued either way.
- ADR 0003 says "the terms question is on the list of facts to verify in post 0". This section is that check. The switch rule's first condition (no one else's work on the subscription token) matches the Legal page. Its second condition (no scheduled job on the subscription token) is stricter than anything I found in Anthropic's text.

## 2. What practitioners mean by LLM-as-judge for code

### Zach Lloyd / Warp

The only primary text I could read is the AI Engineer site's edited write-up of Lloyd's talk "[How to Build a Software Factory That Improves Itself](https://ai.engineer/talks/nKjPBAw_N_0-build-software-factory-that-improves-itself)" (undated, 2026; not a transcript). **[vendor]**

- "Warp runs model-based evaluators on these traces. One looks for redundant tests." The reason given is that a task can produce passing code and an unnecessary test.
- On the cost-against-correctness chart: "The scores came from an LLM judge." The caption shows 94.8% correctness at $6.23 average cost for one configuration.
- "Human grading was something Lloyd recommended, and Warp had yet to add it to that workflow."
- "Lloyd's suggested unit is the cost per pull request, with scoring and benchmark expenditure broken out."

A secondhand recap of his demo says the scoring is retroactive and uses a mid-sized model to hold cost down ([How I AI, 2026-09-18](https://www.chatprd.ai/how-i-ai/inside-warps-software-factory)). His LinkedIn article, X article and podcast episode on the subject could not be read, so nothing from them is used here.

So Warp's judge is offline, pointwise and one narrow question per evaluator. Whether it is binary, how the rubric is written and whether it was checked against people are not stated.

### The design axes

**Pairwise or rubric scoring.**

- Shipped judges score one item against criteria. Qodo's benchmark judge checks each tool comment against a list of 580 injected issues in 100 PRs ([Qodo, 2026-02-04](https://www.qodo.ai/blog/how-we-built-a-real-world-benchmark-for-ai-code-review/)). GitHub's ReviewBench matches findings to a golden set with a published rubric ([GitHub, 2026-10-05](https://github.blog/ai-and-ml/github-copilot/reviewbench-an-open-benchmark-for-ai-code-review/)). Neither reports judge-against-human agreement. **[vendor]**
- Binary over scales: "No complex scoring scales... Just a clear pass or fail decision" ([Hamel Husain](https://hamel.dev/blog/posts/llm-judge/), 2024-10-29, revised 2026-09-01). **[practitioner]**
- "Grade each dimension with an isolated LLM-as-judge", and give the judge a way to answer "Unknown" ([Anthropic, 2026-01-09](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)). **[vendor]** guidance.
- In a benchmark of 26 judge models on code generation, repair and test generation, pairwise comparison beat pointwise scoring, but changing the order of the two responses changed accuracy substantially ([CodeJudgeBench](https://arxiv.org/abs/2507.10535), 2025). **[independent]**
- In a validation on 1,000 pairs of PR reviews, a judge that counted hits against known issues agreed with people about as well as people agreed with each other (kappa 0.53–0.62 against 0.56–0.63). A holistic 1–10 score judge reached only 0.31–0.45 ([SWR-Bench](https://arxiv.org/abs/2509.01494), full text). **[independent]**

**Reference-based or reference-free.**

- Benchmarks that grade reviewers use a reference: known bugs, golden comments or the gold patch. Production reviewers have none. OpenAI says its deployed reviewer has no privileged spec and must avoid over-asserting intent ([OpenAI, 2025-12-01](https://alignment.openai.com/scaling-code-verification/)). **[vendor]**
- Reference-free against a spec is our case, and it is the setting where one study found judges "frequently misclassify correct code implementation as non-compliant or defective" ([Jin and Chen](https://arxiv.org/abs/2603.00539), 2026; the abstract gives no rates). **[independent]**

**Judge on the diff or judge on tests.**

- "We recommend choosing deterministic graders where possible, LLM graders where necessary"; for coding agents, unit tests for correctness and an LLM rubric for quality ([Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)). **[vendor]** guidance.
- "Giving the reviewer repo-wide tools and execution access improves both recall and precision" ([OpenAI](https://alignment.openai.com/scaling-code-verification/)). **[vendor]**
- Tests alone are not enough either. On SWE-bench Verified, 29.6% of test-passing patches behaved differently from the developers' patch, 28.6% of those were judged certainly incorrect, and reported resolution rates were inflated by 6.2 points ([Wang, Pradel and Liu](https://arxiv.org/abs/2503.15223), 2025). **[independent]**
- On 250 SWE-bench Verified issues, a fixed judge's errors changed with the agent version being judged, and eight "upgrades" the judge declared were not confirmed by execution ([Li](https://arxiv.org/abs/2609.34198), 2026, single-author preprint). **[independent]**

**Where the judge sits.**

- Online on each PR, as an advisor. Anthropic's Code Review verifies its own findings to filter false positives and does not approve PRs ([Anthropic, 2026-03-09](https://claude.com/blog/code-review)). **[vendor]**
- Offline over recorded runs, as at Warp, and for scoring benchmarks.
- I found no vendor describing a judge that picks the best of several candidate patches.

**A PR against a ticket.** No practitioner write-up covers a judge that grades a PR against a ticket and gates on it. The closest evidence is the spec-conformance study above and the cross-model review experiment in section 3.

## 3. Known failure modes and which mitigations have evidence

Most foundational studies used GPT-4-era models on general text. Where a result is about code or current models, the table says so.

| Failure mode | Evidence | Applies to a single-PR PASS/BLOCKED judge? |
|---|---|---|
| Position bias | Swapping answer order made one model "win" 66 of 80 queries ([Wang et al.](https://arxiv.org/abs/2305.17926), 2023). On five current judges it was 0.04 or less ([Soumik](https://arxiv.org/abs/2604.23178), TMLR 2026). **[independent]**, general text | Mostly not. It is a pairwise and list problem. |
| Verbosity bias | Named in [Zheng et al.](https://arxiv.org/abs/2306.05685) (2023). Now varies by model: some prefer longer answers, Claude Sonnet 4 slightly prefers shorter ([Soumik](https://arxiv.org/abs/2604.23178)). **[independent]**, general text | Possibly, through long PR text. No code measurement found. |
| Self-preference | In rubric judging with binary verdicts, including a coding benchmark, a judge can be more than 50% more likely to wrongly mark a failed criterion satisfied when the output is its own ([Pombal, Rei and Martins](https://arxiv.org/abs/2604.06996), 2026). With authorship hidden and quality matched, self-preference vanished; labels alone moved scores ([Chae et al.](https://arxiv.org/abs/2608.18091), EMNLP Findings 2026, not code). **[independent]** | Yes, in principle. No study of a same-family builder and reviewer on PRs. |
| Leniency, false PASS | A rubric-guided patch judge had recall 0.93 but precision 0.65 against three human raters, on 115 patches ([Shi et al.](https://arxiv.org/abs/2511.10865), 2025, full text). False acceptance of failed patches rose as agents got stronger ([Li](https://arxiv.org/abs/2609.34198)). **[independent]**, code | Yes. This is the costly error. |
| Over-rejection, false BLOCKED | Judges often mark correct code as non-compliant, and prompts asking for explanations and proposed corrections lead "to higher misjudgment rates" ([Jin and Chen](https://arxiv.org/abs/2603.00539)). **[independent]**, code | Yes. It feeds Rework rounds. |
| Drift | Calibration carried over from an older agent version raised comparison error from 3.8 to 19.5 points ([Li](https://arxiv.org/abs/2609.34198)). Criteria drift: grading outputs changes the grader's criteria ([Shankar et al.](https://arxiv.org/abs/2404.12272), 2024, 9 practitioners). **[independent]** | Yes, when the build model, the review prompt or the Review model changes. |
| Run-to-run inconsistency | Repeated judgments of the same code can disagree, and one-cue prompt edits swing verdicts ([Zhao, Esmaeili and Fard](https://arxiv.org/abs/2604.16790), 2026, code). Version-pinned judges at temperature 0 flipped about 5% of items, about 40% on close calls ([Ayyagari](https://arxiv.org/abs/2609.33044), 2026, general text). **[independent]** | Yes. |
| Sway from author-written text | PR metadata tuned by an attacker got vulnerabilities past Claude Code and CodeRabbit review in 32 of 33 cases; naive templates failed ([Alexopoulos et al.](https://arxiv.org/abs/2603.18740), ICSE 2027). Counterpoint: adversarial code comments had no significant effect on eight models ([Thornton](https://arxiv.org/abs/2602.16741), 2026). **[independent]**, code | Yes, for any text the builder writes that the judge reads. |
| Non-JSON output | Constrained decoding guarantees schema-valid output ([Anthropic structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)). **[vendor]** Strict formats reduced reasoning quality on older models ([Tam et al.](https://arxiv.org/abs/2408.02442), 2024). **[independent]** | Yes, but rare here: 1 of 91 Reviews. **[repo]** |

### Same model judging its own work

The one controlled experiment I found is small: 116 coding tasks, a reviewer that sees the problem and the draft and cannot run tests ([Xiang et al.](https://arxiv.org/abs/2607.21656), 2026). **[independent]**

- Claude reviewing Codex drafts raised the pass rate from 71.6% to 89.7%.
- Codex reviewing Claude drafts lowered it from 91.4% to 82.8%.
- Claude reviewing its own drafts left it at 91.4%.

Read with care: one model pair, one benchmark. It suggests a reviewer helps when it is stronger than the writer, can hurt when it is weaker, and that same-model review may add nothing.

### Mitigations

| Mitigation | Evidence | Strength |
|---|---|---|
| Give the judge execution results | [OpenAI](https://alignment.openai.com/scaling-code-verification/) **[vendor]**; Jin and Chen's filter runs the code and the judge's proposed fix against tests ([abstract](https://arxiv.org/abs/2603.00539)); static-analysis cross-referencing was the best defence in [Thornton](https://arxiv.org/abs/2602.16741) (96.9% detection). **[independent]** | Most consistent direction for code. No single clean number. |
| Different or stronger model as judge | [Xiang et al.](https://arxiv.org/abs/2607.21656): helps only when the reviewer is stronger. | One small study. |
| Panel of judges | A panel of smaller models from different families beat one large judge and cost over seven times less ([Verga et al.](https://arxiv.org/abs/2404.18796), 2024, general text). Ensembling reduces self-preference but does not remove it ([Pombal et al.](https://arxiv.org/abs/2604.06996)). **[independent]** | Real but partial. Not tested on PR review. |
| Hide authorship and the author's own description | [Chae et al.](https://arxiv.org/abs/2608.18091), [Alexopoulos et al.](https://arxiv.org/abs/2603.18740). **[independent]** | Moderate, mixed on size. |
| Binary verdicts, one criterion at a time | [Husain](https://hamel.dev/blog/posts/llm-judge/) **[practitioner]**; SWR-Bench's hit-based judge against its 1–10 judge ([full text](https://arxiv.org/abs/2509.01494)). **[independent]** | Consistent. No controlled study on code. |
| Reasoning before the verdict | Thinking models make better code judges ([CodeJudgeBench](https://arxiv.org/abs/2507.10535)). Explanation-and-fix prompts raised false rejections ([Jin and Chen](https://arxiv.org/abs/2603.00539)). **[independent]** | Conflicting. Not a safe default. |
| Majority vote over repeated runs | Three judge calls gave only a marginal gain in [SWR-Bench](https://arxiv.org/abs/2509.01494). Eleven repeats were needed to match a 50-trial verdict in one general-text study ([Yagubyan](https://arxiv.org/abs/2606.13685), 2026). **[independent]** | Weak. It cancels noise, not a judge's systematic error. |
| Schema-constrained output | [Anthropic docs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs). **[vendor]** | Strong for parsing. No evidence on verdict quality. |
| Re-calibrate against people after changes | [Li](https://arxiv.org/abs/2609.34198) **[independent]**; [Husain and Shankar](https://hamel.dev/blog/posts/evals-faq/) **[practitioner]**. | Evidence that it is needed; the method is practitioner advice. |

Evidence is missing for: leniency drift caused by a judge model update, the effect of strict output schemas on review verdicts, and any same-family builder-and-reviewer study on pull requests.

## 4. How people calibrate a judge

### Agreement with human labels

- Report the true-positive rate and the true-negative rate separately, with human labels as truth. Raw agreement misleads when one class is rare: a judge that always says Pass scores 95% when 5% of cases fail ([Husain](https://hamel.dev/blog/posts/llm-judge/)). **[practitioner]**
- Use human-to-human agreement as the ceiling. In SWR-Bench, three experts and three judge configurations labelled 100 review reports; kappa ran 0.71–0.87 across all pairs ([full text](https://arxiv.org/abs/2509.01494)). **[independent]**
- On 115 patches with three human raters, the judge reached kappa 0.57 overall and 0.75 on the 81 patches where the raters were unanimous. The raters' own agreement was Krippendorff's alpha 0.60. Editing the rubric by hand moved the judge from kappa 0.38 to 0.57 ([Shi et al.](https://arxiv.org/abs/2511.10865), full text). **[independent]**
- No source gives a threshold for "good enough".

### Planted-defect cases

- Every catch rate on injected bugs that I found is a vendor's. Qodo reports 580 injected issues in 100 PRs ([Qodo](https://www.qodo.ai/blog/how-we-built-a-real-world-benchmark-for-ai-code-review/)). **[vendor]**
- The benchmark that describes itself as independent states that its judge "has not been formally calibrated against human annotations" ([Martian methodology](https://github.com/withmartian/code-review-benchmark/blob/main/methodology/full.md)). **[vendor]**, self-described independent.
- Known-good cases matter as much as known-bad ones. SWR-Bench has 500 PRs with a real issue and 500 clean ones; the best tool it tested produced more than one false positive per PR ([full text](https://arxiv.org/abs/2509.01494)). **[independent]**
- I found no independent, replicated catch rate on planted defects, and no evidence on how well planted-defect results predict real ones.

### Inter-run consistency

- Re-run the same input and count verdict flips. Temperature 0 "reduces but does not eliminate" inconsistency ([Yagubyan](https://arxiv.org/abs/2606.13685), 50 trials per item, small general-text models). **[independent]**
- Pinned judges at temperature 0 still flipped about 5% of items ([Ayyagari](https://arxiv.org/abs/2609.33044)). **[independent]**
- No study measures this for a PR-level judge.
- Ours: 10 PR heads were reviewed more than once, and the verdict was the same every time. That is too few to mean much, and those re-runs were not a designed test. **[repo]**, computed from `factory/run-records-backfill.jsonl`.

### Sample sizes

| Source | What was labelled | n |
|---|---|---|
| [SWR-Bench](https://arxiv.org/abs/2509.01494) **[independent]** | Review reports, 3 people | 100 |
| [SWR-Bench](https://arxiv.org/abs/2509.01494) **[independent]** | Pairs of PR reviews | 1,000 |
| [Shi et al.](https://arxiv.org/abs/2511.10865) **[independent]** | Patches, 3 people | 115 |
| [Husain and Shankar](https://hamel.dev/blog/posts/evals-faq/) **[practitioner]** | Per failure mode | 100–200, with 30–50 pass and 30–50 fail in each of the dev and test splits |
| [Anthropic](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) **[vendor]** guidance | Tasks to start with (not judge calibration) | 20–50 |
| [Lee et al.](https://arxiv.org/abs/2511.21140) **[independent]** | Calibration labels for a corrected pass rate with an interval under 0.1 | about 200 |

Split the labels. Husain and Shankar suggest 10–20% for examples in the prompt, 40–45% to tune on and 40–45% held out, and scoring the held-out set once after the prompt is frozen ([FAQ](https://hamel.dev/blog/posts/evals-faq/)). **[practitioner]** Neither code-judge paper above reports a held-out split.

### What a small sample can show

Wilson 95% intervals for an observed 90% rate (**[own arithmetic]**, using the [Wilson score interval](https://en.wikipedia.org/wiki/Binomial_proportion_confidence_interval#Wilson_score_interval)):

| n | Interval | Width |
|---|---|---|
| 30 | 74.4% to 96.5% | 22 points |
| 50 | 78.6% to 95.7% | 17 points |
| 100 | 82.6% to 94.5% | 12 points |
| 200 | 85.1% to 93.4% | 8 points |

For a catch rate, n is the number of real defects, not the number of cases.

- One person with 30 to 100 labels can show that a judge is badly wrong, that it always passes, or that it flips between runs. Reading the disagreements is the main value.
- That sample cannot show a catch rate of "about 90%", or a difference of a few points between two prompts. Detecting a 3-point difference takes about 1,000 items ([Miller, "Adding Error Bars to Evals"](https://arxiv.org/abs/2411.00640), 2024, full text). **[independent]**
- With one labeller there is no human-to-human ceiling, so a kappa against that one person cannot be judged high or low.

## 5. Cost

### List prices

[Anthropic pricing](https://platform.claude.com/docs/en/about-claude/pricing), fetched 2026-11-15, per million tokens. **[vendor]**

| Model | Input | Output | Cache read |
|---|---|---|---|
| Fable 5.2 | $8 | $40 | $0.20 |
| Opus 5.5 | $4 | $20 | $0.20 |
| Sonnet 5.5 | $2 | $10 | $0.10 |
| Haiku 5.5, prompts up to 100k tokens | $0.10 | $0.50 | $0.01 |
| Haiku 5.5, prompts over 100k tokens | $0.50 | $2.50 | $0.05 |

The Batch API gives "a 50 percent discount on both input and output tokens". It suits offline calibration, not a gate.

### What a judge costs per PR

- **Ours.** 91 Reviews in the committed backfill, all on `claude-sonnet-5-5`: mean $0.124, median $0.114, maximum $0.383 per Factory run; about 7 turns, 110k input-plus-cache tokens and 2.5k output tokens. A PR is reviewed 2.07 times on average, so the Review costs about $0.26 per PR. These are client estimates, and on the subscription token they are plan usage, not dollars billed. **[repo]**, computed from `factory/run-records-backfill.jsonl`.
- **GitHub Copilot code review.** "On average, a review costs an estimated $0.25 USD with Lite, $1.50 USD with Balanced, and $10 USD with Max", labelled "estimates only" ([GitHub docs](https://docs.github.com/en/copilot/concepts/agents/code-review)). **[vendor]**
- **Anthropic Code Review.** "Code Review has no flat per-review price"; it is billed on token usage ([docs](https://code.claude.com/docs/en/code-review-costs.md)). The widely repeated $15–25 per review figure appeared only in secondary coverage, so it is not relied on here. **[vendor]**
- **Other products.** Greptile charges $1, $3 or $10 per review by tier ([pricing](https://www.greptile.com/pricing)). CodeRabbit charges per developer per month, $30 to $90 ([pricing](https://www.coderabbit.ai/pricing)). **[vendor]**
- **A measurement, two PRs.** An agentic reviewer on Opus 4.6 cost $0.73 and $1.34 on PRs of 338 and 598 lines, using 0.6M and 1.2M input tokens. A cheaper model cost $0.07 and $0.05 and found nothing on the larger PR ([Kilo, 2026-03-16](https://blog.kilo.ai/p/we-analyzed-how-much-kilo-code-reviewer)). **[vendor]** measuring its own tool.
- **A single-call judge.** At Sonnet 5.5 list prices, one call with 30k input and 2k output tokens is 30,000 × $2 + 2,000 × $10 per million = $0.08; with 5k in and 1k out it is $0.02. On Haiku 5.5 the same two calls are $0.004 and $0.001. Thinking tokens are billed as output and would add to this. **[own arithmetic]**

Our Review costs more than a single call would because it is an agentic run that reads files over several turns. Anthropic's own figure for that overhead is that "agents typically use about 4x more tokens than chat interactions" ([Anthropic](https://www.anthropic.com/engineering/multi-agent-research-system), about research agents). **[vendor]**

No source publishes a measured per-PR cost for a PASS/BLOCKED judge over a diff and a ticket.

### Cheaper patterns

| Pattern | Evidence | Strength |
|---|---|---|
| Small model first, escalate when unsure | A cascade can "match the performance of the best individual LLM (e.g. GPT-4) with up to 98% cost reduction" ([FrugalGPT](https://arxiv.org/abs/2305.05176), 2023, general tasks). A judge cascade that starts with cheap models guaranteed over 80% human agreement on almost 80% of items, on pairwise chat judging, and needs a calibration set ([Jung, Brahman and Choi](https://arxiv.org/abs/2407.18370), 2024). **[independent]** | Real, but not on code review or pass/fail gating. |
| Panel of cheap judges | [Verga et al.](https://arxiv.org/abs/2404.18796): over seven times cheaper than one large judge. **[independent]** | General text only. |
| Call the expensive judge only when two cheap ones disagree | None found. | No evidence. |
| Skip the judge when the check or CI fails | None found. The saving is plain logic: a red check needs no judge. | No measurement. |
| Diff only instead of the whole repo | Context gathering dominated cost in [Kilo's two PRs](https://blog.kilo.ai/p/we-analyzed-how-much-kilo-code-reviewer); [OpenAI](https://alignment.openai.com/scaling-code-verification/) says diff-only review "often misses important context". **[vendor]** | Conflicting; no controlled comparison with cost. |
| Prompt caching of the rubric | Caching a 3k-token rubric saves about $0.006 per Sonnet 5.5 call. **[own arithmetic]** from the price table. | Small next to the diff. |
| Batch API | 50% off, results usually within an hour ([docs](https://platform.claude.com/docs/en/build-with-claude/batch-processing)). **[vendor]** | Useful offline only. |

## What this means for harness-lab

### Where the Review stands

All **[repo]**.

- The Review is an agentic `claude -p` run with Read, Grep and Glob only. It cannot run anything (`factory/review_pr.py`).
- It defaults to the same model as the builder, and every one of the 117 backfilled Run records names `claude-sonnet-5-5` (`.github/workflows/review.yml`, `.github/workflows/implement.yml`).
- Code decides PASS or BLOCKED from typed findings. A blocking finding must quote the Ticket sentence it breaks. `open_question` is the "Unknown" answer that Anthropic's guidance recommends.
- It sees the diff, the Ticket and the repo. It does not see check or CI results. When a Ticket exists it does not see the builder's PR description, which is the "hide the author's own description" mitigation, already in place.
- 91 Reviews: 42 PASS, 46 BLOCKED, 3 with no verdict; one answer that did not parse.
- Nothing measures whether those verdicts were right. There are no human labels, no planted-defect Bench cases, and Run records hold the verdict but not the findings. The Bench has two Bench cases and passes a Bench run only when the check passes and the Review says PASS (`factory/bench.py`).

So the design already matches most of what practitioners recommend. What is missing is any measurement of the judge, and execution evidence in front of it.

### Options, cheapest first

**1. Measure the Review we have.** No change to the factory.

- Label past Reviews by hand: for each blocking finding, was it right; for each PASS, did the PR later need owner commits or a revert. The findings are in the PR report comments. This costs no model spend, only owner time, and yields at most about 44 PRs of labels.
- Add planted-defect cases: take a merged PR, remove one Ticket requirement, and record the expected verdict; keep clean cases alongside. Re-run the Review three times on each to count flips. Forty cases × 3 runs × $0.124 is about $15 on the Bench's metered key. **[own arithmetic]** from our mean Review cost. This needs an expected-verdict field on a Bench case and a Review-only Bench run, which do not exist yet.
- Report true-positive and true-negative rates with the intervals in section 4. At this size the result can show a badly wrong judge and nothing finer.
- One thing to check first: on the Bench the Review reads its standards files from the same clone the build agent edited, while the prompt says they are the base branch (`factory/bench.py`, `review_case`). A calibration built on the Bench inherits that difference.

**2. Show the Review the check results.** A workflow change, no added model spend per PR.

- Run the Review after the check and CI finish, and put their results in front of it, or skip the Review when they fail.
- This has the most consistent support in sections 2 and 3, and it removes Reviews spent on PRs that are already red.
- Cost: the Review would start later, and the Review and CI gate currently share one charge per head, so the ordering needs design. Without option 1 there is no way to tell whether it helped.

**3. Add a second judge.** Recurring spend, and the weakest evidence for our case.

- Either a stronger same-family Review model, or a different-family model beside the Review.
- At list prices Opus 5.5 is twice Sonnet 5.5, so a Review at the same token counts would cost about $0.25 per Factory run and about $0.51 per PR, against $0.26 now. **[own arithmetic]**
- The one controlled study says a reviewer helps only when it is stronger than the writer, and that same-model review changed nothing rather than doing harm. A panel reduces same-family bias without removing it.
- A different-family judge also needs a login the factory does not have: the two logins today are the subscription token and OpenRouter with Claude aliases (`factory/claude.py`).
- Worth considering only if option 1 shows a false-PASS rate that option 2 does not fix.

My recommendation is the same order: 1, then 2, and 3 only on evidence from 1.

## Unknowns

- Whether Anthropic regards its CI docs as the "otherwise explicitly permit" exception in the Consumer Terms. No page says so.
- What "ordinary, individual usage" means for a factory's volume of unattended Factory runs.
- When `--bare` becomes the default for `claude -p`, and whether the factory's pinned Claude Code version would be affected before it is next bumped.
- The Review's real false-PASS and false-BLOCKED rates. No labels exist.
- Whether same-model bias matters for our Review. The rubric-judging study is not about PRs, and the one PR-like experiment found same-model review neutral on a single model pair.
- The Review's run-to-run flip rate. Ten repeated heads with no flips is not a measurement.
- How well planted defects predict the Review's behaviour on real ones. No independent evidence either way.
- Whether `--json-schema` works with the `stream-json` output the factory uses. The docs describe it with `--output-format json` only.
- Whether the owner's plan includes the monthly API credits, which would cover Bench runs made with a key from a linked Console organization.
- What Warp's judge rubric looks like and whether it was checked against people. Lloyd's LinkedIn article, X article and podcast could not be read.
- Anthropic's own per-review cost for Code Review. Only secondary reports of $15–25 were found.
- Savings from judging only on disagreement, or from skipping the judge on a red check. No one has published numbers.
- Several papers here are 2026 preprints read at the abstract only, some by a single author. Their numbers have not been checked against the full text.
