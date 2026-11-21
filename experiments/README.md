# Experiments

An **Experiment** turns one idea into pass/fail checks on a throwaway branch. The idea is a claim from a release note, a doc, a talk or a paper. A human reads the evidence and decides what to keep. No agent merges anything, and a claim that fails is recorded the same way as one that passes.

Each Experiment has one input, its **Experiment request**: `experiments/<slug>/request.md`. The script `experiments/experiment.py` validates a request and runs its checks. It uses the Python standard library only, and it calls no model, no network and no GitHub API.

`experiments/clickhouse-podcast-analytics/` was written before this protocol. It has no request and the runner does not run it.

## The loop

1. **Request.** Copy `experiments/_template/request.md` to `experiments/<slug>/request.md` and fill it in. `<slug>` is lowercase words joined by hyphens. Validate it:

   ```bash
   uv run python experiments/experiment.py validate experiments/<slug>/request.md
   ```

2. **Branch.** Create `experiment/<slug>` from `main`, in a scratch checkout or a git worktree, and commit the request there. Everything the Experiment changes stays on that branch.

3. **Checks.** The owner starts Claude Code by hand, in print mode, with `--max-budget-usd` set to the request's cost cap and a timeout set to the request's timebox:

   ```bash
   timeout <timebox>m claude -p --max-budget-usd <cost cap> \
     "Carry out the Experiment request experiments/<slug>/request.md as experiments/README.md describes."
   ```

   `timeout` is GNU coreutils. On macOS, Homebrew's coreutils installs it as `gtimeout`. Claude Code writes what the request's checks need, makes the smallest change that could make them pass, and commits on the branch. It does not edit the request's checks to make them pass.

4. **Runner.** Run the checks. The runner writes `experiments/<slug>/results.md`:

   ```bash
   uv run python experiments/experiment.py run experiments/<slug>/request.md
   ```

5. **Draft PR.** Open a **draft** PR from `experiment/<slug>` holding the request, the change and `results.md`. No agent marks it ready, approves it or merges it.

6. **A human decides.** The owner reads `results.md`, then either keeps the work or reverts it. See [Revert](#revert).

Nothing starts an Experiment automatically. This protocol adds no label and no workflow, and it leaves the factory's brakes and knobs (`docs/factory/README.md`) as they are.

## The request

A request is a Markdown file with these seven `## ` headings, each present once and not empty. Any other `## ` heading is refused.

- **`Hypothesis`**: the claim, stated so that it can turn out false.
- **`Public sources`**: a list of one or more `https://` URLs, one per `- ` item. Text may follow a URL on the same line.
- **`Checks`**: one to five checks. Each check is a `### ` heading with a short name, one fenced code block holding one shell command, and a line that starts with `Pass means:`.
- **`Cost cap (USD)`**: one number above zero, such as `0.50`.
- **`Timebox (minutes)`**: one whole number above zero.
- **`Model / login`**: the first line is `subscription` or `metered key`. Lines after it say whether the Experiment needs a live model call, and how that call is made.
- **`Revert`**: how to undo the Experiment.

A request holds the idea and its public sources, and nothing else. It never quotes, pastes or links private notes, email, or employer or customer material. A request that needs private text to make sense is not a valid request. The validator cannot judge that rule, so a human checks it before the request is committed. This is a public repo.

## Ceilings

The validator refuses a request whose cost cap or timebox is above these.

| Ceiling | Value |
|---|---|
| Cost cap (USD) | 2 |
| Timebox (minutes) | 60 |

To change a ceiling, edit this table. The validator reads the two values from this file each time it runs, has no flag that overrides them, and refuses every request when it cannot read them. Both values are guesses, not measurements. Revisit them once a few Experiments have run.

## Checks and the runner

- **Exit code 0 is a pass.** Any other exit code is a fail. The `Pass means:` line tells a reader what a pass shows. The runner does not read it.
- **Where a check runs.** Each command runs under `/bin/sh -c`, in the folder that holds the request.
- **What a check can see.** Its environment has three variables: `PATH`, `HOME` set to a new empty temp folder, and `LANG`. Nothing else from the parent's environment reaches it.
- **Per-check timeout.** A check that runs longer than 300 seconds is killed and recorded as a fail with the exit code `timeout`. `--check-timeout <seconds>` changes the limit.
- **Timebox.** The runner stops when the request's timebox is reached. The check that is running is killed, and every check after it is recorded as `not run`. The clock starts when the runner starts. `--elapsed-minutes <n>` tells it how much of the timebox was already spent before it started.
- **Exit code of the runner.** `0` when every check passed, `1` when a check failed or was not run, `2` when the request is invalid. An invalid request runs nothing and writes no `results.md`.

`results.md` records the commit sha, whether the checkout had uncommitted changes (untracked files count, so commit what the checks read before you run them), the request's cap, timebox and login, and each check's command, exit code, result (`pass`, `fail` or `not run`) and duration. It holds no output from the checks. The runner prints the end of each check's output to the terminal instead.

The runner leaves two fields empty, because it cannot know them: the agent's cost and the Claude Code version. Whoever started Claude Code fills them in after that run ends, from its JSON result (`total_cost_usd`) and `claude --version`. The dollar figure is the CLI's own list-price estimate on every login, so `results.md` labels it `client-estimate`.

## No secrets

Experiments never run against secrets or real credentials.

- **Checks get no credentials.** The scrubbed environment holds no `.env` values, no provider key, no GitHub token and no path to the Claude Code login.
- **The validator refuses a check command that reads credentials:**
  - an environment dump: `env`, `printenv`, a bare `set`, `export -p`, `declare -p`;
  - a read of the environment from a program: `environ`, `getenv`, `process.env`;
  - a `.env` file;
  - a credential store: `.claude`, `.config/gh`, `.ssh`, `.aws`, `.netrc`, `.git-credentials`, or the macOS keychain through `security`;
  - `gh auth` and `git credential`;
  - any `$VARIABLE` whose name contains `KEY`, `TOKEN` or `SECRET`.
- **The validator refuses a request that holds a token-shaped string** anywhere in the file.
- **A live model call happens outside the checks.** A check has no login, so it cannot call a model. An Experiment that needs a live call says so in `Model / login`. The call is made once, under that login, and its numbers are saved to a file on the branch with no text from the model. The checks read that file. The call's spend counts against the request's cost cap.

These are guards against mistakes, not a sandbox. The list of refused commands is not complete, and a check runs as your own user, so it can still read a file by its full path. Read the checks of any request you did not write before you run it.

## Revert

Nothing an Experiment does reaches `main`, so reverting it means closing the draft PR and deleting the branch:

```bash
gh pr close <number> --delete-branch
```

With no PR open yet, delete the branch itself: `git branch -D experiment/<slug>`, then `git push origin --delete experiment/<slug>` if it was pushed. If the owner merged an Experiment and wants it gone, that is an ordinary `git revert` of the merge.

## Files

```
experiments/
  README.md                        this file
  experiment.py                    the validator and the runner
  _template/request.md             copy this to start a request
  _template/results.md             the shape of the file the runner writes
  example-budget-cap/request.md    an example request, committed and not run
```

The tests are in `tests/experiments/`. The root `uv run pytest` runs them.
