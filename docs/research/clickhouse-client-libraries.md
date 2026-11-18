# ClickHouse client libraries for Python and Go

Research note for issue #162, checked 2026-11-18. It asks which ClickHouse client libraries are worth using from Python and from Go, and how they compare with plain HTTP through the standard library, which is what `experiments/clickhouse-podcast-analytics/scripts/ch.py` does. Nothing here is a decision: the choice of language and library belongs to a later ticket.

## Summary

- **Python has one client maintained by ClickHouse and one long-lived community client.** `clickhouse-connect` 1.13.0 (ClickHouse Inc., Apache-2.0) speaks HTTP and is tested against server 26.8. `clickhouse-driver` 0.2.11 (community, MIT) speaks the native TCP protocol; its CI stops at server 25.5.
- **Go has two official clients that stack.** `clickhouse-go` v2.51.0 is the high-level one (native TCP by default, HTTP optional, `database/sql` optional) and is tested against 26.8 on Go 1.26 and 1.27. `ch-go` v0.76.0 is the low-level columnar one that `clickhouse-go` uses for encoding. Both are Apache-2.0.
- **Dependency weight is small in both languages.** `clickhouse-connect` adds 5 packages to `uv.lock` on Linux and macOS, all with wheels for Python 3.12 and 3.13. `clickhouse-go` adds 15 modules to `go.mod` and 38 lines to `go.sum`, with no cgo.
- **Bulk inserts.** Every library sends ClickHouse's Native columnar format built from typed values. `clickhouse-connect` and `clickhouse-go` (over HTTP, experimental) can also send a pre-formatted payload such as TSV, which is what the experiment does. `clickhouse-driver` cannot.
- **Settings.** All four take a settings map for the connection and per query.
- **Tests.** No library ships a fake server. They all test against a real ClickHouse. `clickhouse-connect` has an experimental in-process chDB backend behind the same client API. `ch-go` has a `cht` package that starts a local `clickhouse` binary per test, with no Docker.
- **Plain stdlib HTTP keeps** zero dependencies, every server format and setting, and the `X-ClickHouse-Summary` counters the benchmark reads. **It gives up** typed values, Native-format inserts, and the error handling the libraries do. The HTTP interface can return status 200 and then put an exception in the body; `ch.py` does not look for that.
- **chDB bindings exist for both languages.** Python's is the main, most complete binding. Go's is an active release with a `database/sql` driver. Details belong to #161.
- **One server-side fact changes how inserts behave for every client:** ClickHouse 26.2 and later turn `async_insert` on by default.

### How to read this note

Each claim carries a link or one of these labels:

- **[registry]**: read from PyPI's JSON API or the Go module proxy on 2026-11-18.
- **[source]**: read from the library's own repository (README, changelog, CI workflow or code) at its default branch on 2026-11-18.
- **[docs]**: read from the live pages at `clickhouse.com/docs` on 2026-11-18.
- **[measured]**: resolved here in a scratch directory outside this repo, with uv 0.13.7 and Go 1.27.3. Nothing was installed into the Lab's environment and no library was run against a server.
- **[lab]**: read from this repo at commit `159852f`, or from the experiment at `origin/clickhouse-podcast-analytics` commit `4b1b9db`.

Versions move fast here: `clickhouse-connect`, `ch-go` and `chdb` all published a release within two days of this note.

## 1. What the experiment does today

`experiments/clickhouse-podcast-analytics/scripts/ch.py` is about 50 lines over `urllib` **[lab]**:

- It POSTs SQL to `http://127.0.0.1:8123/`, passes settings as URL parameters, and returns the body as text. `rows()` splits TSV, so every value is a string.
- `insert()` sends one `INSERT INTO t (cols) FORMAT TabSeparated` with a payload the caller formatted. The generator builds 100,000-row TSV batches with f-strings and no escaping, which is safe only because it controls the data.
- It parses the `X-ClickHouse-Summary` response header into a dict. The benchmark reads `read_rows` and `read_bytes` from it, with `wait_end_of_query=1` so the header is final.
- It retries any request up to 30 times, one second apart, on a connection error. It raises `ClickHouseError` only on an HTTP error status.
- Each call opens a new connection. There is no compression, no authentication and no query parameters; values are interpolated into the SQL text.

It targets `clickhouse/clickhouse-server:26.8.39.19` **[lab]**. `clickhouse-go`'s CI marks 26.8 as an LTS line **[source]**.

## 2. Python

### Comparison

| | `clickhouse-connect` | `clickhouse-driver` |
|---|---|---|
| Latest release | 1.13.0, 2026-11-16 | 0.2.11, 2026-07-17 |
| First release, cadence | 2022; 1.0.0 on 2026-05-13, then 13 minor releases in six months | 2017; three releases in 2024, one in 2025, one in 2026 |
| Maintainer | ClickHouse Inc. (`author="ClickHouse Inc."`, code owners `@ClickHouse/language-clients`) | Community: the `mymarilyn` GitHub organisation, author Konstantin Lebedev |
| Status in ClickHouse docs | Has its own section, which calls it "a core database driver" | Listed under third-party libraries, which ClickHouse Inc "does not maintain" |
| Licence | Apache-2.0 | MIT |
| PyPI status classifier | 5 - Production/Stable | 4 - Beta |
| Protocol | HTTP (8123/8443), with Native-format bodies | Native TCP (9000/9440) |
| Python | `>=3.10,<3.16` | `>=3.9,<4` |
| Required dependencies | `certifi`, `urllib3`, `lz4` and `backports.zstd` (both only below Python 3.14) | `pytz`, `tzlocal` |
| Compiled parts | Optional Cython extensions; pure-Python fallback. Wheels for CPython 3.10 to 3.15 on Linux, macOS, Windows | Cython extensions. Wheels for CPython 3.9 to 3.14 on Linux, macOS, Windows |
| Server versions in its CI | 26.3, 26.8, 26.9, 26.10 | Newest is 25.5.6.14 |
| Async | `get_async_client()` with the `async` extra (aiohttp) | No; separate wrapper projects exist |

Sources: [PyPI clickhouse-connect](https://pypi.org/project/clickhouse-connect/), [PyPI clickhouse-driver](https://pypi.org/project/clickhouse-driver/) **[registry]**; [clickhouse-connect repo](https://github.com/ClickHouse/clickhouse-connect) (`setup.py`, `CHANGELOG.md`, `.github/CODEOWNERS`, `.github/clickhouse-versions.json`), [clickhouse-driver repo](https://github.com/mymarilyn/clickhouse-driver) (`setup.py`, `CHANGELOG.md`, `LICENSE`, `.github/workflows/actions.yml`) **[source]**; [Python integration](https://clickhouse.com/docs/integrations/python), [third-party client libraries](https://clickhouse.com/docs/interfaces/third-party/client-libraries) **[docs]**.

### Bulk inserts

`clickhouse-connect` ([driver API](https://clickhouse.com/docs/integrations/language-clients/python/driver-api), [advanced inserting](https://clickhouse.com/docs/integrations/language-clients/python/advanced-inserting), [advanced usage](https://clickhouse.com/docs/integrations/language-clients/python/advanced-usage)) **[docs]**:

- `client.insert(table, data, column_names=..., column_oriented=False, settings=...)` takes rows or columns of Python values and sends them as Native format. By default it first runs a metadata query to learn the column types; passing `column_type_names`, or reusing an `InsertContext`, skips that.
- `client.raw_insert(table, column_names, insert_block, settings, fmt, compression)` sends a string, bytes, generator or open file in any server format with no processing. This is the same shape as the experiment's `ch.insert`.
- `insert_file` streams a local file and lets the server parse it. `insert_df` and `insert_arrow` need the pandas or arrow extras.
- Inserts return a `QuerySummary` with `written_rows` and the summary dict.
- An insert is retried once after certain connection closes. The docs say plainly that this is at-least-once: "If the first attempt commits but its response is lost, the retry can insert the same rows again."

`clickhouse-driver` ([quickstart](https://clickhouse-driver.readthedocs.io/en/latest/quickstart.html), [features](https://clickhouse-driver.readthedocs.io/en/latest/features.html)) **[source]**:

- `client.execute('INSERT INTO t (x) VALUES', iterable)` takes any iterable of lists, tuples or dicts and sends blocks in binary columnar form.
- "Inserting data in different formats with FORMAT clause is not supported." A TSV or CSV payload has to be parsed into Python values first.
- Type checking on insert is off by default (`types_check=True` turns it on).

### Query settings and statistics

- `clickhouse-connect`: a `settings` dict on `get_client()` applies to every request, and every query, command and insert method takes its own `settings` dict. HTTP-only parameters such as `wait_end_of_query` and `session_id` go in the same dict. Settings the server marks read-only are dropped with a log warning. `QueryResult.summary` is the "Dictionary decoded from the X-ClickHouse-Summary response header", so the benchmark's `read_rows` and `read_bytes` stay available **[docs]**.
- `clickhouse-driver`: `settings=` on `Client(...)` and on each `execute`. Statistics come from `client.last_query.progress` (rows, bytes, total rows, written rows, server `elapsed_ns`) and `last_query.profile_info` **[source]**.
- Both support server-side query parameters (`{name:Type}`) as well as client-side substitution.

### What they offer for tests

- Neither ships a fake or mock server. Both projects' own test suites start ClickHouse in Docker **[source]**.
- `clickhouse-connect` has `clickhouse_connect.tools.testing.TableContext`, a context manager that creates a table on entry and drops it on exit, and `clickhouse_connect.tools.datagen` with random-value generators per ClickHouse type **[source]**. Neither is described in the docs, and the driver API page says "Methods not documented here aren't considered part of the API, and may be removed or changed."
- `clickhouse-connect` 1.6.0 (2026-07-23) added an experimental chDB backend: `get_client(interface="chdb")` "returns a standard client that runs queries against an embedded chDB engine instead of a ClickHouse server, supporting the full query, insert, streaming, and Arrow client surface". It needs the `chdb` extra, allows one engine per process, and has no async client and no external data **[source]** **[docs]**.
- `testcontainers` 4.15.0 has a `clickhouse` extra. It needs Docker, and the extra depends on `clickhouse-driver` **[registry]**.

### Fit with the Lab's rules

`CODING_STANDARDS.md` requires a Python Project to be a uv workspace member locked in the root `uv.lock`, with a `check` that runs `uv run --locked --package <name> pytest` **[lab]**.

| Dependency | Packages added to a lock for `requires-python >=3.12` |
|---|---|
| `clickhouse-connect` | 6: itself, `certifi`, `urllib3`, `lz4`, `backports-zstd`, and `tzdata` on Windows only |
| `clickhouse-driver` | 4: itself, `pytz`, `tzlocal`, and `tzdata` on Windows only |
| `chdb` | 7: itself, `chdb-core`, `numpy`, `pandas`, `pyarrow`, `python-dateutil`, `tzdata` |
| `clickhouse-connect[chdb]` | 12: the two sets above combined |
| `testcontainers[clickhouse]` | 15, including `docker`, `requests` and `clickhouse-driver` |

**[measured]** with `uv lock` and `uv pip compile --universal --python-version 3.12`.

- `clickhouse-connect` and `clickhouse-driver` both publish wheels for CPython 3.12 and 3.13 on Linux x86_64 and macOS arm64, so CI and the laptop need no compiler. The wheels are 0.25 to 1.75 MB **[registry]**.
- `clickhouse-connect` caps Python at `<3.16`. A lock for `>=3.12` with no upper bound still resolved **[measured]**.
- The root `pyproject.toml` depends on every Python Project so that the root `uv sync` covers them all **[lab]**. Whatever the new Project depends on is installed by every root sync. For the two clients that is a few megabytes. For `chdb` it is the `chdb-core` wheel, 117 MB on macOS arm64 and 185 MB on Linux x86_64, plus pandas, pyarrow and numpy **[registry]**.
- With the optional `clickhouse-driver[lz4]` extra, uv's universal resolution picked `lz4==3.0.1`, because the extra pins `lz4<=3.0.1` for PyPy **[measured]**. I did not look further; it only matters if native-protocol compression is wanted.

### Other Python libraries, briefly

- `asynch` 0.4.0 (2026-08-14, Apache-2.0, a personal repository): asyncio, native protocol.
- `aiochclient` 2.7.0 (2026-06-04, MIT, a personal repository): asyncio over HTTP; the release before it was February 2024.
- `clickhouse-sqlalchemy` (MIT, same author as `clickhouse-driver`): latest upload 2025-07-31. `clickhouse-connect` now ships its own SQLAlchemy dialect and Alembic support.

All three are on the docs' third-party list or built on a library that is **[registry]** **[docs]**.

### chDB from Python

`chdb` 4.5.1 (2026-11-18, Apache-2.0, published by the "chDB Team" with a `clickhouse.com` contact, repository `chdb-io/chdb`) is the main chDB binding; the project's own capability table rates it "Stable main package", and its PyPI classifier is Production/Stable. The engine is the separate `chdb-core` wheel, published only for macOS and Linux on x86_64 and arm64 **[registry]** **[source]**.

## 3. Go

### Comparison

| | `clickhouse-go` v2 | `ch-go` |
|---|---|---|
| Module | `github.com/ClickHouse/clickhouse-go/v2` | `github.com/ClickHouse/ch-go` |
| Latest release | v2.51.0, 2026-11-09 | v0.76.0, 2026-11-17 |
| Maintainer | ClickHouse (GitHub organisation `ClickHouse`) | Same |
| Status in ClickHouse docs | "ClickHouse supports two official Go clients"; this is the high-level one | The low-level one |
| Licence | Apache-2.0 | Apache-2.0 |
| Protocol | Native TCP by default; HTTP with `Protocol: clickhouse.HTTP`. Native-format encoding on both | Native TCP only |
| API | ClickHouse API (`clickhouse.Open`), row or column oriented, struct mapping; or `database/sql` | Column blocks only. "No pooling, reconnects and not goroutine-safe by default, only single connection"; `chpool` adds a pool |
| `go` directive | 1.26.0. README: client `>= 2.50` supports Go 1.26 and 1.27 | 1.26.0 |
| Modules added to `go.mod` | 15: itself plus 14 indirect, including `ch-go`, `klauspost/compress`, `pierrec/lz4`, `google/uuid`, `shopspring/decimal`, `paulmach/orb`, two OpenTelemetry modules | 25: itself plus 24 indirect, including `go.uber.org/zap`, five OpenTelemetry modules, `golang.org/x/tools` |
| `go.sum` lines | 38 | 63 |
| cgo | None | None |
| Server versions in its CI | 26.10, 26.9, 26.8 (LTS), 26.3 (LTS), each on Go 1.26 and 1.27 | v26.4, v26.3 LTS, v26.2, v25.8 LTS |

Sources: Go module proxy `@latest` and `.mod` files **[registry]**; [clickhouse-go repo](https://github.com/ClickHouse/clickhouse-go) (`README.md`, `CONTRIBUTING.md`, `.github/workflows/run-tests.yml`), [ch-go repo](https://github.com/ClickHouse/ch-go) (`README.md`, `query.go`, `cht/cht.go`, `.github/workflows/e2e.yml`) **[source]**; [Go integration](https://clickhouse.com/docs/integrations/go) **[docs]**. Module and `go.sum` counts are **[measured]**: a one-file program importing the library, `go get` at the version shown, then `go mod tidy`.

`clickhouse-go`'s own `go.mod` also requires `testcontainers-go` and the Docker client for its test suite. Those did not reach the scratch module's `go.mod` or `go.sum` **[measured]**.

The docs' own guidance on choosing: `ch-go` "for insert heavy use cases, where millions of inserts are required per second"; `clickhouse-go` "for query workloads focused on aggregations or lower throughput insert workloads" **[docs]**.

### Bulk inserts

`clickhouse-go` ([ClickHouse API](https://clickhouse.com/docs/integrations/language-clients/go/clickhouse-api), README) **[docs]** **[source]**:

- `conn.PrepareBatch(ctx, "INSERT INTO t")`, then `batch.Append(values...)` or `AppendStruct`, then `batch.Send()`. "Batches are held in memory until Send is executed." `Flush` sends what is buffered and keeps the batch open on the native protocol; over HTTP it "is currently a no-op".
- Columnar inserts append whole slices per column.
- With `database/sql` the same thing is `begin -> prepare -> exec in a loop -> commit`. The README calls this interface slower than the ClickHouse API.
- `conn.InsertFormat(ctx, "TabSeparated", "INSERT INTO t", reader)` streams a pre-formatted payload from an `io.Reader`, the closest match to the experiment's `ch.insert`. It is marked experimental ("the API may change or be removed in a future minor release") and works over HTTP only.

`ch-go` **[source]**: an insert is a `ch.Query` with `Body: "INSERT INTO t VALUES"` and `Input` set to typed column values (`proto.ColUInt64`, `proto.ColStr` and so on); `OnInput` refills the columns to stream block after block. There is no row API and no reflection.

### Query settings and statistics

- `clickhouse-go`: `Options.Settings` for the connection, and `clickhouse.Context(ctx, clickhouse.WithSettings(clickhouse.Settings{...}))` per query. A batch uses the context given to `PrepareBatch`. Read statistics arrive through context callbacks: `WithProgress`, `WithProfileInfo`, `WithLogs` **[docs]**.
- `ch-go`: `ch.Query` has `Settings`, `Parameters`, `QueryID`, and callbacks `OnProgress`, `OnProfile`, `OnProfileEvents`, `OnLog` **[source]**.
- Both support server-side query parameters.

### What they offer for tests

- Neither ships a fake server. `clickhouse-go`'s contributing guide says: "Do not mock `driver.Conn` or `driver.Rows` in tests — test against a real ClickHouse instance." Its own tests need Docker and use testcontainers-go **[source]**.
- `ch-go` exports `github.com/ClickHouse/ch-go/cht`. `cht.New(t)` writes a config into `t.TempDir()`, starts the `clickhouse` binary found through `CH_BIN` or `PATH`, and returns the server's TCP and HTTP addresses. No Docker is involved. It skips the test when no binary is found and `CH_E2E` is unset, and fails when `CH_E2E=1` **[source]**. A check that must exit non-zero on failure would need `CH_E2E=1`. `ch-go`'s own CI gets the binary by copying `/usr/bin/clickhouse` out of the server's Docker image.
- `github.com/testcontainers/testcontainers-go/modules/clickhouse` v0.45.0 (2026-11-05, MIT) starts a server container and returns a DSN. Its `go.mod` lists 47 indirect modules, mostly the Docker client **[registry]**.

### Fit with the Lab's rules

`CODING_STANDARDS.md` requires a Go Project to commit `go.sum` and to pin linters as `tool` dependencies run with `go tool`; `projects/agent-identity/go.mod` pins `go 1.27.3` and `honnef.co/go/tools/cmd/staticcheck` **[lab]**.

- Both clients need Go 1.26 or newer, so a `go 1.27.x` directive works, and CI reads the Go version from the Project's `go.mod` **[lab]**.
- Neither client adds a `tool` dependency or needs cgo, so `go vet`, `go tool staticcheck` and `go test -race` run as they do for agent-identity.
- A test helper changes the picture more than the client does: `cht` adds little (its imports are already in `ch-go`'s module set), while the testcontainers module adds the Docker client's module tree to `go.sum`.

### Other Go libraries, briefly

- `mailru/go-clickhouse` v2.5.1 (2026-01-18, MIT): `database/sql` over HTTP, few dependencies, slow cadence.
- `vahid-sohrabloo/chconn` v3.2.0 (2026-10-28, MIT, a personal repository): low-level columnar driver; requires Go 1.27.0.
- `uptrace/go-clickhouse` v0.3.1: last release 2023-02-16, last commit 2023-10-01. Not maintained in practice.

All three are on the docs' third-party list **[registry]** **[source]** **[docs]**.

### chDB from Go

`github.com/chdb-io/chdb-go/v2` v2.4.0 (2026-11-12, Apache-2.0) binds `libchdb` through purego, so ordinary builds stay cgo-free, and offers a `database/sql` driver. The engine either comes from the machine (an installer script puts `libchdb` in a system path) or from the build (a blank import of `github.com/chdb-io/chdb-go/lib/embedded` carries a compressed engine in the binary and extracts it on first run). The chDB project's capability table, dated 2026-09-28, rates the Go binding "Active release", one step below Python's "Stable main package", with no typed Arrow API and client-side parameter interpolation **[registry]** **[source]**.

## 4. Plain HTTP through the standard library

This is the experiment's approach, and it is a supported one: "The HTTP interface lets you use ClickHouse on any platform from any programming language in the form of a REST API. The HTTP interface is more limited than the native interface, but it has better language support." ([HTTP interface](https://clickhouse.com/docs/interfaces/http)) **[docs]**

### What it keeps

- **No dependencies.** Nothing is added to `uv.lock` or `go.sum`.
- **Every server format.** The server parses inserts and formats results, so TSV, CSV, JSONEachRow, Parquet and the rest all work with no client code.
- **Every setting**, as a URL parameter per request.
- **The summary counters.** `X-ClickHouse-Summary` carries `read_rows`, `read_bytes`, `written_rows`, `written_bytes`, `elapsed_ns` and `memory_usage`.
- **Server-side query parameters**: `{name:Type}` in the SQL and `param_name=value` in the URL. `ch.py` does not use them, but nothing stops it.
- **Sessions and compression**: a `session_id` parameter; `Content-Encoding` and `Accept-Encoding` with gzip, which both standard libraries have.
- In Go, `net/http` also gives connection reuse for free. Python's `urllib.request` opens a connection per call.

### What it gives up

- **Typed values.** Results are text. `ch.py` returns lists of strings and the callers convert. A library returns ints, dates, decimals, arrays and maps.
- **Native-format inserts from typed values.** The caller formats the payload and owns the escaping. The libraries build binary columns and check them against the table's types.
- **Catching every error.** "Because of limitations of the HTTP protocol, a HTTP 200 response code doesn't guarantee that a query was successful." The error is "injected into the body as plain text", and "The only way to catch all errors is to analyze the HTTP body before parsing it using the required format." `wait_end_of_query=1` reduces this but "doesn't completely solve the problem" **[docs]**. `ch.py` raises only on an HTTP error status **[lab]**, so a failure after the headers were sent would come back as rows. `clickhouse-connect` raises `StreamFailureError` for mid-stream failures **[docs]**.
- **A considered retry policy.** `ch.py` retries every request on a connection error, inserts included, which can insert a batch twice. `clickhouse-connect` separates reads from writes and documents the at-least-once case.
- **Error codes as data.** The server sends `X-ClickHouse-Exception-Code`; `ch.py` keeps only the message text.
- **Native-protocol features**: the progress, profile and log packets sent while a query runs. `clickhouse-connect` is HTTP only, so it does not get these either.

The libraries do not unlock anything the experiment needs and cannot get: its inserts map onto `raw_insert` or `InsertFormat` one for one, and its summary counters map onto `QueryResult.summary`. What a library adds is typed rows and error handling, at the cost of a few locked packages.

## 5. A server-side fact that affects every client

ClickHouse 26.2 changed the default of `async_insert` from false to true. The server source records it as `{"26.2", false, true, "Enable async inserts by default."}` ([Settings.cpp](https://github.com/ClickHouse/ClickHouse/blob/master/src/Core/Settings.cpp)) **[source]**. `wait_for_async_insert` still defaults to true, so an insert returns after its data is flushed. `clickhouse-go`'s README spells out the effect: "with a low insert rate, each `INSERT` takes 50 ms or more, with all clients", and advises batching or `async_insert=0` **[source]**.

The experiment runs on 26.8, so this applies to it. Whether its 100,000-row batches take the async path was not checked. A Project that loads test data in its check may want to set `async_insert` explicitly, whichever client it uses.

## Unknowns

- **Nothing was run against a server.** Compatibility with 26.8 rests on each project's CI matrix, not on a test here.
- **`clickhouse-driver` on server 26.x.** Its CI matrix ends at 25.5.6.14. The native protocol negotiates revisions, so it may well work, but no source says so.
- **`ch-go` on 26.8 directly.** Its end-to-end matrix lists 26.4, 26.3, 26.2 and 25.8. `clickhouse-go`, which uses it for encoding, does test 26.8.
- **Read statistics from `clickhouse-go` over HTTP.** The progress and profile callbacks are documented without saying which transport they need. I found no handling of `X-ClickHouse-Summary` in `conn_http.go` or `conn_http_query.go` and did not read the other HTTP files. Treat `read_rows` and `read_bytes` over HTTP as unconfirmed for Go.
- **Speed.** No benchmark was run. The figures in the libraries' READMEs (for example `ch-go`'s "Up to 700x faster than HTTP API") are their own claims and are not repeated as findings.
- **Which ClickHouse version chDB carries.** `chdb` 4.5.1 requires `chdb-core>=26.11.1`. The `chdb-go` README says the first two fields of a chdb-core release name the ClickHouse line, which would make this the 26.11 line, newer than the experiment's 26.8. The ClickHouse docs' chDB page still says "powered by ClickHouse v25.8.2.1". How chDB's behaviour differs from a 26.8 server is #161's question.
- **How large the embedded chDB engine is in a Go build.** Not measured.
- **The testcontainers-python ClickHouse module.** Only its PyPI metadata was read; its source file was not found at the expected path.
- **Team size behind each library.** Ownership and commit recency were checked; the number of active maintainers was not.
- **Docs lag the code in places.** The Python pages in the `ClickHouse/clickhouse-docs` repository say "current as of the clickhouse-connect release 0.9.2", so this note used the live site instead. The Go docs still show `AsyncInsert` examples that the README calls deprecated, and the docs' chDB Go page uses the v1 import path.
