# What the factory's agent can run during its build turn

Research note, checked 2026-11-18, for Ticket #163 (map #159). It establishes what the build agent in Implement and Rework can reach and run, so that #164 can decide where a ClickHouse for a Project's `check` comes from. Nothing here is a decision.

Nothing was run for this note: no workflow, no factory run, no model call. Repo facts are quoted by path and line from `main` at `5cddc6b`. Outside facts are quoted from GitHub's and Claude Code's own documentation and source, fetched on 2026-11-18. Where a claim would need a live run to confirm, it is listed under "Not established".

## Summary

- **The agent has an unrestricted shell on the runner.** The factory starts Claude Code with `--permission-mode bypassPermissions` and denies only `WebFetch`, `WebSearch`, `Agent`, `Task` and `Read(//proc/**)`. Claude Code's sandbox is off by default and nothing in the repo turns it on. The runner gives passwordless `sudo`, and Docker is preinstalled. So the agent can start Docker, reach a port on `localhost`, and download a binary with `curl`. The comment in `factory/ticket.py` that says the agent may "not reach the web" is true of the two web tools only.
- **A job-level `services:` container starts before the first step and lives until the job ends.** Every step can reach it on `localhost:<mapped port>`, including the steps that hold the App token. It gets no secret unless the workflow maps one into it. The token-holding steps run only the factory's own scripts and never talk to it.
- **`services:` cannot read a step's output.** Its expressions see `github`, `needs`, `strategy`, `matrix`, `vars` and `inputs`, and no `steps` and no `hashFiles`. Implement and Rework learn the Ticket's Project in a step, which is too late. An empty `image` string is GitHub's documented way to make a service conditional.
- **Any change under `.github/` is made by hand.** The App has no Workflows permission, and the prompts tell the agent not to edit `.github/`. A service, or a step that starts Docker, is not something a factory Ticket can build.
- **Rules touched.** `CODING_STANDARDS.md` says a check "runs against committed, locked dependencies only": an image tag or a `curl | sh` download is neither. CI treats any failed job as a rework input, so a failed image pull would charge one of the two rework rounds. CI's job limit is 10 minutes. `ci.yml` holds no secrets, so a Docker Hub pull there is unauthenticated.
- **Verify on a bootstrap** runs the new `check` once in the same job, after the agent, with credentials removed from its environment. It needs the same ClickHouse the check expects to be reachable at that point, and a check that tolerates whatever the agent left in a shared server.

## 1. Tools and permissions the agent has

### What the factory passes

`factory/ticket.py` `build` (lines 398-407) runs the agent with `disallowed_tools=DENIED_TOOLS`, `may_edit=True` and `cwd` set to the work checkout. The deny list is line 74:

```python
DENIED_TOOLS = ["WebFetch", "WebSearch", "Agent", "Task", "Read(//proc/**)"]
```

`factory/claude.py` `command` (lines 102-113) builds:

```
claude -p --output-format stream-json --verbose --model <m> --max-budget-usd <b>
       --setting-sources project --disallowedTools <deny list> --permission-mode bypassPermissions
```

No `--allowedTools` is passed for the build, and no `--tools`. The repo tracks no `.claude/settings.json` and no `.mcp.json`, so `--setting-sources project` loads no permission rules, no sandbox setting and no MCP server. The prompt is passed as text on stdin (`factory/claude.py:138`).

`agent_env` (`factory/claude.py:42-63`) copies the step's environment, drops `GH_TOKEN`, `GITHUB_TOKEN`, the Actions runtime and OIDC tokens, both factory secrets and every `ANTHROPIC_*` variable (lines 34-35, 43-44), then sets only the chosen Claude login. Everything else in the step's environment passes through, including `PATH`, `GITHUB_ENV` (`docs/factory/README.md:252`) and any variable a workflow step sets in `env:`.

What is on the machine when the agent starts, in Implement (`.github/workflows/implement.yml`): `uv` (line 67), the work checkout (lines 81-85), Go only when the Project's `go.mod` is already on the branch (lines 95-99), and Claude Code `2.1.319` (lines 35, 101-102). Rework is the same (`.github/workflows/rework.yml:76`, `116-123`). The job runs on `ubuntu-latest` with a 60-minute limit (`implement.yml:45-46`, `rework.yml:51-52`).

### What those flags allow

From Claude Code's documentation:

- `bypassPermissions` "disables permission prompts and safety checks so tool calls execute immediately". "Deny rules block in every mode, including `bypassPermissions`." ([permission modes](https://code.claude.com/docs/en/permission-modes))
- A bare tool name in `--disallowedTools` "removes the matching tools from Claude's context". ([CLI reference](https://code.claude.com/docs/en/cli-reference)) So the agent has no `WebFetch`, `WebSearch` or `Agent` tool. `Bash`, `Read`, `Edit` and `Write` remain ([tools reference](https://code.claude.com/docs/en/tools-reference)).
- Denying the web tools does not close the network: "using WebFetch alone doesn't prevent network access. If Bash is allowed, Claude can still use `curl`, `wget`, or other tools to reach any URL." ([permissions](https://code.claude.com/docs/en/permissions))
- "The sandbox is off by default." It is turned on with `/sandbox` or `sandbox.enabled` in a settings file. ([sandboxing](https://code.claude.com/docs/en/sandboxing)) The factory does neither, so Bash commands have no filesystem or network boundary from Claude Code.
- `Read(//proc/**)` is an absolute-path deny rule. Read deny rules apply to the file tools and to "file commands Claude Code recognizes in Bash, such as `cat`, `head`, `tail`, `sed`, and `tee`". "They don't apply to ... arbitrary subprocesses that read or write files indirectly, like a Python or Node script that opens files itself." ([permissions](https://code.claude.com/docs/en/permissions)) This matches `docs/factory/README.md:191-193`, which already says the build agent "can see its own Claude Code login".
- Claude Code "refuses to start in `bypassPermissions` mode when running as root or under `sudo`". ([permission modes](https://code.claude.com/docs/en/permission-modes)) The factory starts it as the runner's ordinary user. That does not stop the agent's Bash commands from calling `sudo` themselves.
- Bash timeouts: a foreground command gets two minutes by default and ten at most. When a foreground command reaches its timeout, "Claude Code moves it to the background instead of stopping it". In a `-p` run whose prompt is passed as text, a background command's time limit defaults to 10 minutes, and Claude can pass up to 2 hours. ([tools reference](https://code.claude.com/docs/en/tools-reference))
- A `-p` run "can stay open to wait for background work that Claude started": for a background command the main conversation started, "the run waits until the command exits or reaches its time limit. Claude then takes one more turn with the outcome." ([headless](https://code.claude.com/docs/en/headless)) A ClickHouse server the agent starts as a background Bash command and does not stop would hold the Build step open that long. A container started with `docker run -d` is not a background Bash command: the command returns at once.

From GitHub's documentation:

- "The Linux and macOS virtual machines both run using passwordless sudo." ([GitHub-hosted runners reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners))
- `ubuntu-latest` is the Ubuntu 24.04 image ([runner-images README](https://github.com/actions/runner-images/blob/main/README.md)). Its software list for image `20261111.370.1` has Docker Client 28.0.4, Docker Server 28.0.4, Docker Compose 2.38.2, `curl` and `wget`. It lists PostgreSQL and MySQL as installed and disabled. It lists no ClickHouse. Go is under "Cached Tools" only. ([Ubuntu2404-Readme](https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md))
- GitHub's own examples run `docker build`, `docker login` and `docker push` in plain `run:` steps on `ubuntu-latest`, without `sudo`. ([Publishing and installing a package with GitHub Actions](https://docs.github.com/en/packages/managing-github-packages-using-github-actions-workflows/publishing-and-installing-a-package-with-github-actions))
- A public repository's standard runner is 4 CPU, 16 GB RAM, 14 GB SSD, and "free and unlimited on public repositories". ([GitHub-hosted runners reference](https://docs.github.com/en/actions/reference/runners/github-hosted-runners))

### Docker, a service container, a download

**Established**

- **Start Docker: yes.** The agent's Bash tool runs any command, Docker is on the runner, and `sudo` needs no password. `docker run -d` returns at once, so it does not meet the Bash timeout.
- **Reach a job's service container: yes, on `localhost`.** Implement and Rework run their steps directly on the runner machine (no `container:` key). GitHub: "When running jobs directly on the runner machine, you can access service containers using `localhost:<port>` or `127.0.0.1:<port>`", and "You need to map ports on the service container to the Docker host." ([service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers)) With the sandbox off, nothing in Claude Code stands between a Bash command and `localhost`.
- **Download a binary: yes.** `curl` is on the image and the network is open to Bash. ClickHouse's quick install is `curl https://clickhouse.com/ | sh`, which downloads "a single binary for your operating system"; `./clickhouse server` starts a server and `./clickhouse` starts `clickhouse-local`. ([ClickHouse quick install](https://clickhouse.com/docs/get-started/setup/self-managed/quick-install))
- **A locked dependency that embeds the engine needs nothing new.** `uv` is installed before the agent starts and `uv run --locked` already fetches from PyPI during the turn. chDB is "an in-process OLAP SQL Engine powered by ClickHouse"; `chdb` 4.5.1 depends on `chdb-core`, whose Linux x86_64 wheel is 185 MB ([PyPI chdb](https://pypi.org/project/chdb/), [PyPI chdb-core](https://pypi.org/project/chdb-core/)). For Go, `chdb-go` either loads a `libchdb` installed with `curl -sL https://lib.chdb.io | bash`, or carries the engine in the build through `import _ "github.com/chdb-io/chdb-go/lib/embedded"` ([chdb-go README](https://github.com/chdb-io/chdb-go/blob/main/README.md)).
- **A variable a workflow step sets reaches the agent's commands.** `agent_env` passes through everything it does not drop, so a step-level `env:` entry such as a ClickHouse port would be in the agent's shell.

**Not established**

- That the agent, given only today's prompt, would choose to start Docker or wait for a server. The prompt says to run `projects/<name>/check` "until it passes" (`factory/ticket.py:165-166`). What the check does is up to the check.
- How long a pull of the server image takes on a runner. Docker Hub lists `clickhouse/clickhouse-server:latest` at 309 MB compressed for amd64 ([Docker Hub tag API](https://hub.docker.com/v2/repositories/clickhouse/clickhouse-server/tags/latest)). No run was made to time it.
- The Claude Code pages describe the current release (`2.1.327` on npm today). The factory pins `2.1.319`. The version gates the pages name for the behaviour quoted above are all at or below `2.1.295`, but the pinned build was not run.
- Whether a server the agent daemonizes inside a Bash command survives that command. `docker run -d` does not depend on this.

## 2. A job-level `services:` container and the token-holding steps

**Established**

- **It starts before every step.** The runner adds "Initialize containers" as a pre-job step, ahead of the action steps ([`JobExtension.cs`](https://github.com/actions/runner/blob/main/src/Runner.Worker/JobExtension.cs), the `preJobSteps.Add(... displayName: "Initialize containers" ...)` block). GitHub "creates a fresh Docker container for each service configured in the workflow, and destroys the service container when the job completes." ([service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers)) In Implement that means it is pulled and started before Preflight and Claim, so a run that the daily cap stops or that Claim refuses has still pulled the image. A job whose `if:` is false is skipped whole and starts nothing.
- **It is alive during every step of the job**: Claim and Publish (App token), Build (Claude login), Verify (neither) and the run record (App token). "Steps in a job can communicate with all service containers that are part of the same job."
- **It holds no secret unless the workflow gives it one.** A service receives only its own `env:`, `credentials:`, `volumes:` and `options:`. The `secrets` context is available to `services.<id>.env` and `services.<id>.credentials` and not to `services` itself ([contexts reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)). A step's `env:` is not shared with it.
- **The token-holding steps do not use it.** Claim, Publish, Release and the run record run `python -m factory.ticket ...` and `python -m factory.run_record ...` (`implement.yml:69-79`, `143-193`). None of them connects to a database. Only the agent's commands and Verify would.
- **It must sit in the workflow file.** GitHub: "you cannot create and use service containers inside a composite action." The preflight is a composite action (`.github/actions/factory-preflight/action.yml:53-54`), so a service cannot go there.
- **Its expressions cannot see a step.** `jobs.<job_id>.services` may use `github, needs, strategy, matrix, vars, inputs`, with no `steps` context and no `hashFiles` ([contexts reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)). Implement and Rework read the Project from `run-out/context.json` in a step (`implement.yml:87-91`, `rework.yml:108-112`), after services have started.
- **A conditional service is documented.** "If `jobs.<job_id>.services.<service_id>.image` is assigned an empty string, the service will not start. You can use this to set up conditional services." ([workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)) What each workflow could key it on:
  - Implement: the `issues` event puts the Ticket ("The issue itself") in `github.event.issue` ([webhook events and payloads](https://docs.github.com/en/webhooks/webhook-events-and-payloads#issues)), so its `project:<name>` label is within reach of the expression. See "Not established" for the one gap.
  - Rework: the event is the pull request. `publish` opens the draft with no labels (`factory/github.py:160-164`), so nothing in the `github` context names the Project.
  - CI: the `project` job has `matrix.project` (`.github/workflows/ci.yml:56-59`), and `matrix` is available to `services`.
- **A step can do what `services:` cannot.** A step's `if:` may use `steps` and `hashFiles`, which is how Go is installed today (`implement.yml:95-99`, `ci.yml:65-69`). A `run:` step can call `docker run -d`.
- **The runner waits only for a container that has a health check.** It waits while a service reports `starting` and fails the job with "Failed to initialize container" if it ends unhealthy; a container with no `HEALTHCHECK` counts as ready at once ([`ContainerOperationProvider.cs`](https://github.com/actions/runner/blob/main/src/Runner.Worker/ContainerOperationProvider.cs)). The ClickHouse server Dockerfile declares none ([Dockerfile.ubuntu](https://github.com/ClickHouse/ClickHouse/blob/master/docker/server/Dockerfile.ubuntu)). GitHub's PostgreSQL example passes `--health-cmd` in `options:` ([PostgreSQL service containers](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers)).
- **The image's `default` user needs a password to accept network connections.** "The user `default` has disabled network access by default in the case none of `CLICKHOUSE_USER`, `CLICKHOUSE_PASSWORD`, or `CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT` are set." ([ClickHouse Docker README](https://github.com/ClickHouse/ClickHouse/blob/master/docker/server/README.md)) A throwaway test password written in the workflow is not a GitHub secret.
- **The agent can change the service.** It can reach the Docker daemon, so it can stop the container, `docker exec` into it or start another on the same port.

**Established, and not new with a service**

- The agent's step runs before Publish and the run record in the same job, on the same VM, as a user with passwordless `sudo`. It holds no GitHub token during its own step (`factory/claude.py:34-35`). The factory's own checkout, `uv` and `PATH` are all writable by it, and Publish later runs from them with the App token. `docs/factory/README.md:252` already records one case of this (`GITHUB_ENV`). A service container adds nothing to this: the agent's shell already reaches further than the container does. This reading comes from the documented `sudo` access and the step order. It was not demonstrated.

**Not established**

- Whether `services.<id>.image` accepts a digest (`name@sha256:...`). Docker accepts one; GitHub's page says only "the Docker Hub image name or a registry name".
- That `github.event.issue.labels` lists every label on the Ticket at the moment of a `labeled` event. GitHub's page documents the `issue` object and folds its properties away, so the list was not read there. `rework.yml:31` reads `github.event.pull_request.labels.*.name` in the same way for a pull request.
- What a ClickHouse image does on the runner's network beyond serving its ports. It is third-party code running beside the job for its whole life.

## 3. Brakes and public-repo safety rules touched

`docs/adr/0005-label-only-factory-start-and-no-secrets-for-forks.md` (line 3): the factory "starts only on a label the owner applies" and "PRs from forks never get secrets". `docs/adr/0007-factory-scripts-from-the-default-branch-agents-without-github-token.md` (line 3): the workflow and `factory/` scripts "always come from the default branch", and every job splits into "steps that hold the App token and run no agent, and agent steps that hold only the Claude Code login".

**Established**

| Rule | Where | What a ClickHouse service or download touches |
|---|---|---|
| The factory cannot change its own workflows | `docs/factory/README.md:194-195`, `docs/factory/setup.md:49-50`, the prompts (`factory/ticket.py:172`, `194`) | A `services:` block or a Docker step in `implement.yml`, `rework.yml` or `ci.yml` is a change by hand. A factory Ticket cannot build it. The factory doc and `factory/*.py` can still be factory-root Tickets. |
| Factory scripts from the default branch (ADR 0007) | `rework.yml:17-18`, `implement.yml:14-16` | A service added to Implement or Rework takes effect only once it is on `main`. A pull request cannot change it for its own run. |
| CI holds no secrets and runs fork PRs' code (ADR 0005) | `ci.yml:4-7`, `16-17`; `docs/factory/README.md:174-177` | A service in `ci.yml` starts for fork pull requests too and holds nothing. An unauthenticated Docker Hub pull is limited to "100 per IPv4 address or IPv6 /64 subnet" per 6 hours ([Docker Hub pull limits](https://docs.docker.com/docker-hub/usage/pulls/)). Logging in to raise it would put a secret in `ci.yml`. |
| The agent never holds a GitHub token (ADR 0007) | `factory/claude.py:34-35`; `docs/factory/README.md:182-188` | Unchanged by a service: nothing passes a token to it. |
| The agent can see its own Claude login | `docs/factory/README.md:191-193` | A binary the agent downloads and runs, or an engine loaded in the test process, runs inside the agent's environment, which holds the Claude login. That is the same position as every locked dependency the check runs today. A service container does not inherit that environment. |
| The check rule | `CODING_STANDARDS.md:8`: a check "runs against committed, locked dependencies only" | An image named by tag and a `curl \| sh` download are not committed or locked. A wheel in `uv.lock` or a module in `go.sum` is. A service the workflow provides sits outside the check script, and the rule does not say how to treat that. |
| Stop after two rework rounds | `docs/factory/README.md:151`; `factory/ci_gate.py:135-143`, `228-229` | The gate makes one finding "per job whose conclusion is failure", whichever step failed. A failed image pull or an unhealthy service fails the CI job and charges a round, with the instruction "make the Project check pass". `timed_out` and `cancelled` do not charge one. |
| CI's 10-minute job limit | `ci.yml:55` | Image pull, server start and the check share those 10 minutes in each `check <name>` job. Implement and Rework have 60 (`implement.yml:46`, `rework.yml:52`). |
| CI checks every Project when `.github/` changes | `factory/ci_projects.py:27`, `35-39` | The pull request that adds a service runs every Project's check. An unconditional service in the `project` job would start for every Project's job (`ci.yml:50-59`). |
| Dollar cap per agent run | `docs/factory/README.md:159-160` | A service costs no tokens. A background server the agent leaves running costs one more turn when it ends (section 1). |
| Daily run cap, one Ticket at a time, draft only, a human merges | `docs/factory/README.md:147-158` | Not touched. The cap check runs after services start (section 2), so a capped run still pulls the image. |

**Not established**

- Whether Docker Hub's pull limit is ever reached from GitHub's shared runner addresses. GitHub's docs mention credentials "to increase your DockerHub rate limit" and state no exemption.
- How the owner wants the check rule read for a service the workflow provides. That is a rule to write, not a fact to find.

## 4. The Verify step on a bootstrap

What it is today (`factory/ticket.py:421-451`; `implement.yml:119-141`; `rework.yml:141-159`; `docs/factory/README.md:118-141`): only when the run is a bootstrap, after Build and before Publish, the job installs Go if the new `go.mod` exists and then runs `./projects/<name>/check` in the work checkout. The step sets the GitHub tokens and both factory secrets to empty, and `verify` also drops them and every `ANTHROPIC_*` variable from the script's environment (lines 445-446). The call has no timeout of its own (line 447), so the 60-minute job limit is the only one. A non-zero exit fails the job and nothing is published.

On a bootstrap the agent is told the factory "runs `{check}` after you finish", and for a Go Project that it should not install a toolchain (`factory/ticket.py:203-214`). A Python Project has `uv` for the whole turn; a Go Project has no Go until after the agent finishes (`docs/factory/README.md:126-128`).

**Established**

- **Verify runs in the same job as the agent**, so a job-level service is still up and reachable on `localhost` when it runs.
- **Verify can start Docker or download a binary itself.** It is an ordinary process on the runner with the network open. The dropped variables are credentials only.
- **A step-level `env:` value reaches the check.** `verify` passes through everything it does not drop.
- **Verify needs whatever CI needs.** The same script runs in CI's `check <name>` job on the pull request (`ci.yml:70-73`), on a fresh runner. If ClickHouse comes from the workflow, it has to be provided in three places: Implement, Rework and CI. If the check brings its own (a locked dependency, or a container or binary the script starts), no workflow changes.
- **A shared server is not clean when Verify runs.** With a job-level service, the agent's own runs of the check and Verify's run talk to the same server. CI gets a fresh one. The check has to create and drop what it uses, or use a database name of its own.
- **The first run's bootstrap is the only time the factory runs the check.** Afterwards the agent is told to run it and CI runs it (`docs/factory/README.md:134-136`). So the agent's turn on every later Ticket needs the same ClickHouse within reach.
- **A bootstrap changes nothing about a conditional service.** In Implement the `project:<name>` label is on the Ticket before the run starts, bootstrap or not. In Rework the `github` context has nothing that names the Project (section 2).

**Not established**

- Whether a real check with ClickHouse fits CI's 10 minutes. It depends on the test data, which the map lists as not yet specified.
- Whether the agent on a Go bootstrap would try the check anyway. It has Docker and `curl` during its turn and no Go.

## 5. What each route would touch

Facts only, for #164. "By hand" means an owner commit, because the factory cannot push under `.github/`.

| Route | Workflow files, by hand | Agent's turn | Verify on a bootstrap | CI | Rules it meets |
|---|---|---|---|---|---|
| Job-level `services:` | `implement.yml`, `rework.yml`, `ci.yml` | Reaches it on `localhost` | Same service, already used by the agent | Starts per `check` job; conditional through `matrix` | Starts before Preflight; no step outputs; Rework has no Project in `github`; pull failure charges a rework round; check rule silent |
| A step that runs `docker run -d` | The same three files | Reaches it on `localhost` | Same container | A step with `if:` on `hashFiles` or `matrix` | Can follow Claim and read the Project; same pull limits and rework charge; check rule silent |
| The check starts its own container | None | Agent's shell can run Docker | Runs as written | Runs as written | An image tag is not a locked dependency; a digest in the script would be committed; needs Docker on the laptop |
| The check downloads the `clickhouse` binary | None | Agent's shell can run `curl` | Runs as written | Runs as written | `curl \| sh` is not a locked dependency; the binary runs inside the agent's environment |
| An embedded engine as a locked dependency (chDB) | None | `uv` or Go fetches it like any dependency | Runs as written | Runs as written | Fits the check rule as written; a 185 MB wheel per fresh runner; it is the engine in-process, not a server |

## Unknowns

- No timing: image pull, server start, and a check with test data were not measured on a runner.
- The pinned Claude Code `2.1.319` was not run. The documentation read is for the current release.
- Docker Hub's pull limit on shared runner addresses, and digest pinning in `services.<id>.image`, are not confirmed by GitHub's pages.
- Whether chDB behaves like a ClickHouse server for what the Project wants to learn (for example MergeTree engines, materialized views, the HTTP and native interfaces) was not examined. That belongs to #164.

## Sources

Repo, at `5cddc6b`: `factory/ticket.py`, `factory/claude.py`, `factory/github.py`, `factory/ci_gate.py`, `factory/ci_projects.py`, `.github/workflows/implement.yml`, `.github/workflows/rework.yml`, `.github/workflows/ci.yml`, `.github/workflows/ci-gate.yml`, `.github/actions/factory-preflight/action.yml`, `docs/factory/README.md`, `docs/factory/setup.md`, `docs/adr/0005-label-only-factory-start-and-no-secrets-for-forks.md`, `docs/adr/0007-factory-scripts-from-the-default-branch-agents-without-github-token.md`, `CODING_STANDARDS.md`.

GitHub, fetched 2026-11-18:

- <https://docs.github.com/en/actions/tutorials/use-containerized-services/use-docker-service-containers>
- <https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers>
- <https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax> (`jobs.<job_id>.services`)
- <https://docs.github.com/en/actions/reference/workflows-and-actions/contexts> (context availability)
- <https://docs.github.com/en/actions/reference/runners/github-hosted-runners>
- <https://docs.github.com/en/webhooks/webhook-events-and-payloads#issues>
- <https://docs.github.com/en/packages/managing-github-packages-using-github-actions-workflows/publishing-and-installing-a-package-with-github-actions>
- <https://github.com/actions/runner-images/blob/main/README.md> and <https://github.com/actions/runner-images/blob/main/images/ubuntu/Ubuntu2404-Readme.md>
- <https://github.com/actions/runner/blob/main/src/Runner.Worker/JobExtension.cs> and <https://github.com/actions/runner/blob/main/src/Runner.Worker/ContainerOperationProvider.cs>

Claude Code, fetched 2026-11-18:

- <https://code.claude.com/docs/en/cli-reference>
- <https://code.claude.com/docs/en/permission-modes>
- <https://code.claude.com/docs/en/permissions>
- <https://code.claude.com/docs/en/sandboxing>
- <https://code.claude.com/docs/en/tools-reference>
- <https://code.claude.com/docs/en/headless>

ClickHouse, chDB and Docker, fetched 2026-11-18:

- <https://clickhouse.com/docs/get-started/setup/self-managed/quick-install>
- <https://github.com/ClickHouse/ClickHouse/blob/master/docker/server/README.md> and <https://github.com/ClickHouse/ClickHouse/blob/master/docker/server/Dockerfile.ubuntu>
- <https://hub.docker.com/v2/repositories/clickhouse/clickhouse-server/tags/latest>
- <https://pypi.org/project/chdb/>, <https://pypi.org/project/chdb-core/>, <https://github.com/chdb-io/chdb-go/blob/main/README.md>
- <https://docs.docker.com/docker-hub/usage/pulls/>
