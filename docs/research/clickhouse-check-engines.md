# Ways to run real ClickHouse inside a check

Research note for issue #161, checked 2026-11-18. It asks how a Project's `check` can run against real ClickHouse on a GitHub-hosted `ubuntu-latest` runner and on the owner's laptop, and what each way costs. Nothing here is a decision.

## Summary

Every option below ran the experiment's whole schema and passed the same feature probes: materialized views into AggregatingMergeTree, ReplacingMergeTree with `FINAL`, the dictionary, the projection, the text index, TTL and background merges. None of them is ruled out on features. They differ in which ClickHouse version they carry, how they are pinned, and how much of the repo has to change.

- **`services:` container.** Exact 26.8.39.19. A service can be switched off per matrix entry: an empty `image` string means "the service will not start", and the `matrix` context is available there. It is the option that changes the most: `ci.yml`, the script that builds the matrix, the two workflows where the agent runs the check, and a separate start-up path for the laptop.
- **The check starts the pinned image itself.** Exact 26.8.39.19, pinned by digest inside the Project. One path for the laptop and the runner, no workflow change. Needs Docker wherever the check runs. About 4 to 5 s to ready on the laptop with the image present; 281 MB to pull on a runner.
- **Pinned binary (`clickhouse local`, or `clickhouse server` from the same file).** Exact 26.8.39.19, pinned by a sha256 the release API publishes. No Docker. `clickhouse local` starts in about 0.05 s and a bare server answers in about 0.4 s. 239 MB to download on a runner unless cached. The check has to fetch and verify the file itself, and the check rule has no wording for that yet.
- **chDB, Python.** Fits the check rule as written: the engine is a wheel in `uv.lock`, and nothing in CI or the factory changes. It does not track 26.8. The only version that imports on this laptop is chdb-core 26.11.1, which is built from ClickHouse's unreleased `main`. Its merge pool is 4 threads against the server's 32.
- **chDB, Go.** Also fits the rule: the engine is a Go module in `go.sum`. The published engine modules stop at the ClickHouse 26.7 line, which upstream no longer supports.

| | `services:` | check starts image | pinned binary | chDB Python | chDB Go |
|---|---|---|---|---|---|
| ClickHouse version | 26.8.39.19 | 26.8.39.19 | 26.8.39.19 | 26.11.1.1 (from `main`); 26.9 and 26.7 lines exist | 26.7.2.1 |
| All seven features | yes (ran) | yes (ran) | yes (ran) | yes (ran) | yes (ran) |
| Background merge pool | 32 | 32 | 32 | 4 | 4 |
| Pinned by | image digest in the workflow | image digest in the Project | version plus sha256 in the Project | wheel hashes in `uv.lock` | `h1:` hashes in `go.sum` |
| Download on a runner (amd64) | 281 MB image | 281 MB image | 239 MB archive | 185 MB wheel, plus pandas and pyarrow | 117 MB module |
| Start-up, measured on the laptop | not run in Actions | 4.3 to 4.8 s | 0.05 s local, 0.4 s server | 0.1 to 0.4 s import | 2.5 s first run, then 0.06 s |
| Needs Docker | on the runner; laptop needs its own | yes, both | no | no | no |
| Plain `pull_request`, fork PRs | yes, public pull | yes, public pull | yes, public download | yes, PyPI | yes, Go proxy |
| Workflow changes | `ci.yml`, `implement.yml`, `rework.yml`, matrix script | none | none (a cache step is optional) | none | none |
| Same path on laptop and runner | no | yes | yes (one file per OS) | yes | yes |

Start-up times are from the owner's laptop, not from a hosted runner. Download time on a runner was not measured for any option.

### How to read this note

Each claim carries one of these labels:

- **[ran]**: I ran it on 2026-11-18. Section 7 says what and where.
- **[docs]**: read from the vendor's own documentation page, linked.
- **[registry]**: read from a first-party registry or release API: Docker Hub, PyPI, the GitHub releases API, or the Go module proxy.
- **[repo]**: read from this repo at commit `159852f` (`main`), or from the experiment at `4b1b9db` on the `clickhouse-podcast-analytics` branch.

The laptop is an Apple-silicon Mac on macOS 27.2.1 with Docker Desktop (Linux VM, aarch64, 12 CPUs). Hosted runners are x86_64, so everything marked **[ran]** was run on arm64, not on the architecture CI uses.

## 1. What the check has to support

From `experiments/clickhouse-podcast-analytics/schema/01_tables.sql` and `experiments/clickhouse-podcast-analytics/schema/02_rollups.sql` **[repo]**:

- two materialized views, each writing `TO` an AggregatingMergeTree table with `SimpleAggregateFunction` and `AggregateFunction(uniq, …)` columns;
- `ReplacingMergeTree(ingested_at)` with a `PRIMARY KEY` shorter than `ORDER BY`, read with `FINAL`;
- a `FLAT` dictionary sourced from a ClickHouse table, read with `dictGet`;
- a projection (`by_podcast`) inside a MergeTree table;
- a text index (`TYPE text(tokenizer = splitByNonAlpha)`), queried with `hasToken`;
- a row TTL of two years;
- background merges, because the experiment's lessons are about what a query sees before and after parts merge.

The experiment pins `clickhouse/clickhouse-server:26.8.39.19` **[repo]**. That release was published on 2026-11-17, and the 26.8 line had patch releases on the 14th, 16th and 17th **[registry: [ClickHouse releases](https://github.com/ClickHouse/ClickHouse/releases)]**. Upstream lists 26.10, 26.9, 26.8 and 26.3 as supported and 26.7 as not **[docs: [SECURITY.md](https://github.com/ClickHouse/ClickHouse/blob/master/SECURITY.md)]**. The newest release is v26.10.5.57; there is no 26.11 release yet **[registry]**.

## 2. A `services:` container in the workflow

**What it is.** The workflow asks the runner to start the image beside the job. The check does not start anything; it expects a server at an address.

**Features and version.** It is the same image the experiment uses, so the server probes in section 7 apply: all seven features, 26.8.39.19 **[ran, as a plain `docker run`, not inside Actions]**.

**Switching it on for one matrix entry.** This works on paper, from two statements in the workflow syntax reference **[docs: [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)]**:

> If `jobs.<job_id>.services.<service_id>.image` is assigned an empty string, the service will not start.

> You can use this to set up conditional services, similar to the following example.

and the context table lists `github, needs, strategy, matrix, vars, inputs` for `jobs.<job_id>.services`, with no special functions **[docs: [contexts](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts)]**. So `image: ${{ matrix.clickhouse }}` is allowed, and `hashFiles(...)` is not. The decision cannot be made by looking for a file inside the job, the way `ci.yml` decides whether to set up Go. It has to arrive in the matrix, which means `factory/ci_projects.py` would emit objects such as `{"project": "x", "clickhouse": "<image>@sha256:…"}` with an empty string for the other Projects, where today it emits a list of names **[repo]**. I did not run a workflow, so the combination is untested.

**Other facts that shape it** **[docs, same pages unless linked]**:

- A job that runs on the runner machine, as `ci.yml`'s does, must map the service's ports and reach it at `localhost:<port>`.
- GitHub's PostgreSQL example sets `--health-cmd` options under the comment "Set health checks to wait until postgres has started" ([tutorial](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers)).
- Service containers need an Ubuntu runner on GitHub-hosted runners.
- `services.<id>.command` and `.entrypoint` exist.
- The image's `default` user has no network access unless a user or password is set, or `CLICKHOUSE_SKIP_USER_SETUP=1` ([ClickHouse Docker docs](https://clickhouse.com/docs/install/docker)). The experiment's compose file sets that variable **[repo]**.

**Pinning.** By digest in the workflow file: `clickhouse/clickhouse-server@sha256:a42be7a55bbbe15a062afb72759564be70c92bf020265bf8d8011af73c95b98c` is the multi-arch digest that the tags `26.8`, `26.8.39` and `26.8.39.19` all pointed at on 2026-11-18 **[registry: [Docker Hub](https://hub.docker.com/r/clickhouse/clickhouse-server/tags)]**. The branch tag `26.8` moves with each patch release **[docs]**. The pin lives outside the Project folder.

**Size.** The amd64 image is 281,467,885 bytes compressed; the `-alpine` variant is 250 MB and `-distroless` 249 MB **[registry]**. Nothing in `ci.yml` caches image layers, so each job would pull it again **[repo]**.

**Fork PRs and no secrets.** The image is public, so no credentials are needed. On rate limits **[docs: workflow syntax, under `container.image`]**:

> However, GitHub-hosted runners are not subject to these limits based on an agreement between GitHub and Docker.

**What it costs in the repo.** This is the heavy part.

- `ci.yml` gains the `services:` block and the matrix changes shape.
- The agent runs `projects/<name>/check` inside `implement.yml` and `rework.yml`, and the factory runs a new Project's check in `implement.yml` **[repo: `docs/factory/README.md`]**. Those jobs would need the same service, or the agent could never see a green check.
- `services:` exists only in Actions. The laptop needs its own way to start a server, so there are two start-up paths to keep in step.
- The image reference would be in up to three workflow files.

## 3. The check starts the pinned image itself

**What it is.** The check runs `docker run` (or a library such as testcontainers does), waits for the server, runs the tests and removes the container.

**Features and version.** All seven features on 26.8.39.19 **[ran]**. With merges left alone, twenty small inserts into the rollup merged down to one part within seconds, and expired TTL rows were gone after a 30 s wait without any `OPTIMIZE` **[ran]**.

**Start-up.** With the image already present, the server answered `/ping` and had loaded both schema files from `/docker-entrypoint-initdb.d` 4.8 s after `docker run` in one run and 4.3 s in another **[ran]**. The experiment's README reports about 6 s for `make up` **[repo]**.

**Pinning.** The same digest as above, but committed inside the Project, next to the check. The digest of the image on the laptop matched Docker Hub's **[ran]**.

**Docker on the runner.** The Ubuntu 24.04 image lists Docker 28.0.4 and the Ubuntu 26.04 image lists Docker 29.4.2 **[registry: [runner-images](https://github.com/actions/runner-images)]**. `ubuntu-latest` is moving from 24.04 to 26.04, with the move planned to finish on 2026-11-19 ([announcement](https://github.com/actions/runner-images/issues/14748)).

**Fork PRs.** Same as section 2: a public pull, no secrets, and the rate-limit exemption for hosted runners.

**Libraries.** `testcontainers` 4.15.0 on PyPI has a `clickhouse` extra, and `github.com/testcontainers/testcontainers-go/modules/clickhouse` is at v0.45.0 **[registry]**. They would be ordinary locked dependencies. The image reference is still a string in the test code. I did not run either.

**What it costs.** No workflow change. Docker has to be running on the laptop, and reachable from the agent's shell in `implement.yml` and `rework.yml`. The agent runs with `--permission-mode bypassPermissions` on `ubuntu-latest` **[repo: `factory/claude.py`]**, so nothing obvious stops it, but I did not test that. The amd64 image requires the x86-64-v3 instruction level (AVX2 and others) **[docs: [ClickHouse Docker docs](https://clickhouse.com/docs/install/docker)]**; I did not confirm what hosted runners provide.

## 4. A pinned binary: `clickhouse local`, or a server from the same file

**What it is.** ClickHouse ships one executable. `clickhouse local` runs SQL in-process with no server, and `clickhouse server` from the same file is the server. The docs say clickhouse-local is "executed using the same `clickhouse` binary that runs the ClickHouse server" **[docs: [clickhouse-local](https://clickhouse.com/docs/operations/utilities/clickhouse-local)]**.

**Features and version.** `clickhouse local --path <dir> --queries-file <file>` ran the whole schema and every probe on 26.8.39.19, both with the Linux binary inside the pinned image and with the macOS arm64 release binary run directly on the laptop **[ran]**. Background merges ran inside the `clickhouse local` process: the merge pool reported 32 threads, the same as the server, and parts merged without `OPTIMIZE` **[ran]**. The docs page does not mention MergeTree, merges, views or dictionaries under `clickhouse local` either way, so this rests on the runs.

**Three ways to use it.**

- *One process per run.* Data in `--path` survives between runs, but merges only happen while a process is alive. "Only one instance can work with the same directory at a time" **[docs]**.
- *Kept alive and reached over a port.* `clickhouse local` in 26.8.39.19 has `--listen_host`, `--tcp_port` and `--http_port`, and `SYSTEM START LISTEN TCP` let `clickhouse client` query it from another process **[ran]**. At that point it is close to running the server.
- *The server from the same file.* `clickhouse server -- --path=… --tcp_port=… --http_port=… --listen_host=127.0.0.1`, with no config file and no Docker entrypoint, answered its first query 0.42 s after launch in the Linux container and `/ping` after 1.16 s on macOS **[ran]**.

**Start-up.** `clickhouse local` took 0.04 to 0.06 s for a whole create-insert-select run in the Linux container **[ran]**. On macOS the very first launch of the freshly downloaded binary took 7 s; I did not time a second launch on its own.

**Pinning.** The GitHub release for `v26.8.39.19-lts` carries each asset's sha256 in the API's `digest` field and a `.sha512` file beside each archive **[registry]**:

| asset | bytes | use |
|---|---:|---|
| `clickhouse-common-static-26.8.39.19-amd64.tgz` | 238,609,170 | Linux x86_64 (the runner); holds `usr/bin/clickhouse` |
| `clickhouse-common-static-26.8.39.19-arm64.tgz` | 219,402,796 | Linux arm64 |
| `clickhouse-macos-aarch64` | 177,596,803 | Apple-silicon Mac, a bare executable |

The same amd64 archive, by name and length, is served at `packages.clickhouse.com/tgz/lts/` and `/tgz/stable/` **[ran: HEAD requests]**. I downloaded the macOS binary and its sha256 matched the API's digest **[ran]**. The quick-install script (`curl https://clickhouse.com/ | sh`) picks a binary for the OS and offers no version choice **[docs: [quick install](https://clickhouse.com/docs/install/quick-install)]**, so it cannot be the pin. The unpacked Linux arm64 binary is 752 MB **[ran]**.

**Fork PRs.** A public download with no credentials.

**What it costs.** No workflow change is required. The check, or a small script it calls, has to pick the asset for the OS, download it, verify the hash and keep it somewhere outside git. Without a cache that is 239 MB per CI job. `CODING_STANDARDS.md` says a check "runs against committed, locked dependencies only" and gives a lockfile example for each language **[repo]**; a version and a hash committed in the Project is the same idea, but the rule has no words for it.

## 5. chDB, the embedded engine

chDB is "a fast in-process SQL OLAP Engine powered by ClickHouse" **[docs: [chDB](https://clickhouse.com/docs/chdb)]**. The engine is now a separate package, `chdb-core`; `chdb` is a 1.8 MB pure-Python wrapper that depends on it **[registry: [PyPI chdb](https://pypi.org/project/chdb/), [PyPI chdb-core](https://pypi.org/project/chdb-core/)]**.

### Which ClickHouse it tracks

- chdb-core's first two version fields are the ClickHouse line it carries; the third is its own counter **[docs: [chdb-go README](https://github.com/chdb-io/chdb-go)]**.
- Releases on PyPI: 26.1.0, 26.3.0, 26.5.0, 26.7.0, 26.7.3, 26.9.0, 26.11.1. There is no 26.8 **[registry]**.
- `SELECT version()` returned 26.7.2.1 on chdb-core 26.7.3, 26.9.2.1 on 26.9.0 and 26.11.1.1 on 26.11.1 **[ran]**.
- The 26.11.1 release notes say it was synced to upstream `main` at commit `e497200`, and that "the generated `26.11.1.1-testing` string is not an exact identifier for that commit" **[registry: [chdb-core releases](https://github.com/chdb-io/chdb-core/releases)]**. Upstream has not released 26.11, so the newest chDB is ahead of any released ClickHouse.
- The chDB docs landing page still says "v25.8.2.1". It is out of date against the packages.

### Features

Every probe passed on chdb-core 26.11.1, 26.9.0 and 26.7.3, and through the Go binding **[ran]**. Background merges run: with merges left alone, parts merged and expired TTL rows disappeared within 30 s. Differences from the server that showed up:

- The merge pool is 4 threads, against 32 **[ran]**.
- From 26.11.1, "New embedded MergeTree tables default to LZ4 and single-threaded INSERT; implicit column statistics are disabled unless configured" **[registry: release notes]**.
- One engine per process, bound to one data path **[docs: chdb-go README]**.
- On 26.11.1 the rollup was still at two parts and 400 rows after 30 s, on macOS and on Linux, where the server had reached one part and 200 rows **[ran]**. Both are valid "eventual" states.

### Python

- **Pinning.** `uv.lock` already stores a sha256 per wheel **[repo]**, so the engine would be locked like any other dependency. This is the check rule exactly as written: `uv run --locked --package <name> pytest`.
- **Size.** The manylinux x86_64 wheel for 26.11.1 is 184,891,473 bytes; macOS arm64 is 117,069,223 **[registry]**. `chdb-core` requires `pandas>=2.1.0` and `pyarrow>=13.0.0`, so those and numpy enter the lock **[registry]**. A fresh Linux venv with only chdb-core was 728 MB on disk **[ran]**.
- **Start-up.** `import chdb` took 0.1 to 0.4 s on Linux; the first-ever import on macOS took 5.4 s and later ones 0.16 s. Opening a session and running the first query took about 0.02 s **[ran]**.
- **The laptop.** The macOS arm64 wheels of chdb-core 26.9.0 and 26.7.3 failed to import on macOS 27.2.1 with `mis-aligned LINKEDIT string pool`. The same versions imported and passed in a Linux container. 26.11.1 imported on both **[ran]**. Since `uv.lock` holds one version for all platforms, Python chDB on this laptop means 26.11.1 for now.
- **Client code.** clickhouse-connect 1.13.0 opened the embedded engine with `get_client("chdb:///<path>")` and returned a `ChdbClient` that created a MergeTree table, inserted and queried, with a `summary` on the result **[ran]**. The chdb 4.5.0 notes say "clickhouse-connect 1.6.0 and later ships its own chDB backend". So Python code written against clickhouse-connect could run against either a server or chDB.
- **Fork PRs.** PyPI downloads, no secrets. `setup-uv` enables its cache by default on hosted runners for `pull_request` events, keyed on `uv.lock` among other files **[docs: [setup-uv README](https://github.com/astral-sh/setup-uv)]**. Its caching page says "By default, the entire uv cache is persisted across runs", and that dropping pre-built wheels is the opt-in `prune-cache` input ([caching](https://github.com/astral-sh/setup-uv/blob/main/docs/caching.md)). `ci.yml` does not set it **[repo]**, so the 185 MB wheel should be cached. I did not see that happen.

### Go

- **How the engine arrives.** chdb-go v2 is built on purego, not cgo. A blank import of `github.com/chdb-io/chdb-go/lib/embedded` brings the engine in as a Go module per platform; on first run it "is extracted to a cache directory" **[docs: chdb-go README]**.
- **Pinning.** `go.sum` got `h1:` lines for `lib/embedded` and for each of the four platform modules **[ran]**. That is the check rule as written for Go.
- **Version.** The proxy lists only `v0.260700.1` and `v0.260703.1` for the engine modules, both the ClickHouse 26.7 line **[registry: proxy.golang.org]**. With `chdb-go/v2` v2.4.0 and `lib/embedded` v0.260703.1, `SELECT version()` returned 26.7.2.1 and every probe passed, on macOS 27.2.1 **[ran]**. Upstream no longer supports 26.7.
- **A newer engine.** `CHDB_LIB_PATH` points chdb-go at any `libchdb`, and chdb-core releases carry `linux-x86_64-libchdb.tar.gz` (184 MB) with a `SHA256SUMS` file **[docs, registry]**. That gives 26.9 or 26.11, but the pin becomes a hash the check verifies, as in section 4, not `go.sum`. I did not run this.
- **Size.** The `linux-amd64` engine module zip is 117,375,301 bytes and `darwin-arm64` is 82,710,332. A plain `go build` from an empty module cache downloaded only the module for the build's platform. The extracted engine took 326 MB in the cache directory, and the test binary was 87 MB **[ran]**.
- **Start-up.** The first session took 2.5 s, which includes extracting the engine; the next run took 0.06 s **[ran]**.
- **Shutdown.** The README warns that a binary built with `-race` can crash on exit with a session open and merges in flight, and says to close every session and call `chdb.Shutdown()` first **[docs]**. A Go check that runs tests with `-race` would need that.
- **Fork PRs.** Go proxy downloads, no secrets. `ci.yml` already passes the Project's `go.sum` to `setup-go` as the cache key **[repo]**.

## 6. Things that apply to every option

**Merge timing is not deterministic, on any engine.** Right after twenty inserts the rollup held 1,200 rows on the server and 400 on chDB 26.11.1. On the server the next query, a moment later, already saw a single merged part **[ran]**. A test that asserts "before the merge" will race unless it holds merges still. This worked the same on the server, on `clickhouse local`, on all three chdb-core versions and through chdb-go **[ran]**:

- `SYSTEM STOP MERGES <table>`, then twenty inserts, then a 12 s wait: still 20 parts and 4,000 rows in the rollup, 200 rows through `GROUP BY`; downloads 1,100 raw and 1,000 with `FINAL`.
- `SYSTEM START MERGES <table>`, then a 15 s wait: one part and 200 rows in the rollup. The two downloads parts had not merged; `OPTIMIZE TABLE … FINAL` merged them in the other probe.

**No secrets, fork PRs.** "With the exception of `GITHUB_TOKEN`, secrets are not passed to the runner when a workflow is triggered from a forked repository" **[docs: [events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows)]**. Every option here needs only public downloads, so all of them work on a plain `pull_request` run.

**Caches.** A pull request run can restore caches from its base branch, "including base branches of forked repositories"; a repository gets 10 GB by default, and entries unused for 7 days are removed **[docs: [dependency caching](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching)]**. A 239 MB binary archive, a 185 MB wheel or a 117 MB Go module fits.

**The 10-minute job limit.** The standard runner for a public repository has 4 CPUs, 16 GB of RAM and 14 GB of disk **[docs: [GitHub-hosted runners](https://docs.github.com/en/actions/reference/runners/github-hosted-runners)]**. Once the engine is on the machine every option starts in under 5 s. The unknown is the download, which I could not measure.

### What stands out

This is my reading, not a decision.

- If the Project should run the same ClickHouse as the experiment, the choice is between the image and the binary. Both give 26.8.39.19 and one path for laptop and runner when the check starts them itself.
- If the Project should fit the check rule with no new machinery, chDB through Python does that today, at the price of running an engine built from unreleased `main` with a smaller merge pool.
- `services:` is workable per matrix entry, but it is the only option that needs changes in three workflows and a second path for the laptop.

## 7. What I ran

All on 2026-11-18. Scratch files lived outside the repo and were deleted; containers had unique names and non-default ports and were removed.

**The probe.** The experiment's two schema files, unchanged, then:

1. 200 rows into `brands`, then `dictGet('podcast.brands_dict', 'name', toUInt64(5))`.
2. Twenty inserts of 10,000 rows into `brand_mentions`; row count, distinct keys and `sum(mentions)` in `brand_mentions_daily`; active parts from `system.parts`.
3. 1,000 downloads plus 100 redelivered ids with a later `ingested_at`; `count()` with and without `FINAL`; `uniqMerge(downloads)` from the rollup.
4. `EXPLAIN indexes = 1` on a podcast-first query, looking for `ReadFromMergeTree (by_podcast)`.
5. 5,000 transcript rows, a `hasToken` count, and `EXPLAIN indexes = 1` on a token that is absent, looking for the `text_tokens` skip index dropping the part.
6. 100 transcript rows dated 2020; count of them straight after insert, after a 30 s wait, and after `OPTIMIZE TABLE … FINAL`.
7. `BackgroundMergesAndMutationsPoolSize` from `system.metrics`; part and row counts after the wait; then `OPTIMIZE … FINAL` on the rollup and on `downloads`.

A second probe did the `SYSTEM STOP MERGES` / `START MERGES` sequence in section 6.

**Results.** Every row passed every step: `dictGet` returned `brand5`; `sum(mentions)` was 200,000 over 200 keys; downloads were 1,100 raw, 1,000 with `FINAL` and 1,000 by `uniqMerge`; the plan read from `by_podcast`; the text index dropped 1 of 1 parts for the absent token; the 100 expired rows were there after insert and gone after the wait; `OPTIMIZE … FINAL` left 200 rollup rows and 1,000 downloads.

| engine | where | `version()` | merge pool | stop/start probe |
|---|---|---|---:|---|
| server image, by digest | Docker Desktop, linux/arm64 | 26.8.39.19 | 32 | passed |
| `clickhouse local`, binary in that image | Docker Desktop, linux/arm64 | 26.8.39.19 | 32 | passed |
| `clickhouse local`, `clickhouse-macos-aarch64` | macOS 27.2.1 | 26.8.39.19 | 32 | not run |
| chdb-core 26.11.1, Python 3.13 | macOS 27.2.1 and Linux aarch64 | 26.11.1.1 | 4 | passed on both |
| chdb-core 26.9.0, Python 3.13 | Linux aarch64 (import fails on macOS 27.2.1) | 26.9.2.1 | 4 | passed |
| chdb-core 26.7.3, Python 3.13 | Linux aarch64 (import fails on macOS 27.2.1) | 26.7.2.1 | 4 | passed |
| chdb-go v2.4.0 with `lib/embedded` v0.260703.1, Go 1.27.3 | macOS 27.2.1 | 26.7.2.1 | 4 | passed |

**Other runs.**

- Server image: time from `docker run` to `/ping` and to the last schema object existing (4.8 s and 4.3 s).
- Inside the pinned image: three timed `clickhouse local` runs; `SYSTEM START LISTEN TCP` in `clickhouse local` and a query from `clickhouse client`; a bare `clickhouse server` on other ports, timed to its first answer.
- On macOS: downloaded `clickhouse-macos-aarch64` from the release, compared its sha256 with the API's digest, ran the probe with `clickhouse local`, and started a bare server on other ports.
- Go: `go get` of the two modules into a scratch module cache; a second `go build` from an empty cache to see which engine modules a build downloads.
- clickhouse-connect 1.13.0 with chdb-core 26.11.1 on macOS: `get_client("chdb:///…")`, create, insert, query.
- HEAD requests for the amd64 archive on `packages.clickhouse.com` and on the GitHub release.

## 8. What I could not verify

- **Anything inside GitHub Actions.** No workflow was run. That covers: the empty-image service combined with a matrix value built by `fromJSON`; whether an empty image is skipped cleanly when `ports` and `options` are also set; whether a job waits for a service's health check; and pull or download times on a hosted runner.
- **x86_64.** Every run was on arm64. The amd64 image, archive, wheel and Go module were checked for existence and size only.
- **Whether a service container can take files from the checkout.** My understanding is that the runner starts services before the job's steps, so `/docker-entrypoint-initdb.d` could not be filled from the repo and the check would apply the schema itself. I did not find a doc sentence that says so.
- **Docker from the agent's shell** in `implement.yml` and `rework.yml`. Read from the code, not tried.
- **Cache behaviour for the large files**: that `setup-uv` really keeps the chdb-core wheel and `setup-go` the engine module. Read from their docs and from `ci.yml`, not seen in a run.
- **Whether hosted runners meet the amd64 image's x86-64-v3 requirement.**
- **The macOS import failure's cause.** I saw the error on one machine and one OS version, and did not look for it in the chDB issue tracker. Other chdb-core versions (26.7.0, 26.5.0 and older) were not tried.
- **How chDB differs from the server beyond what the probes touch.** The probes cover the experiment's schema at a few thousand rows. They do not cover the experiment's 5.3 million rows, its benchmark, or settings and system tables it does not use.
- **`CHDB_LIB_PATH` with a newer `libchdb`** for Go, and both testcontainers modules. Read, not run.
- **The Docker Official Image `clickhouse`** (a different repository from `clickhouse/clickhouse-server`). Its newest 26.8 tag was 26.8.36.3 on 2026-11-18 **[registry]**; I did not look further.
