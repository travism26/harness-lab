# ClickHouse podcast analytics

## 1. What this is

A personal, for-fun ClickHouse learning experiment in the podcast ad-measurement domain:
which podcasts mention which brands, transcript segments, downloads by region and device,
and campaign windows. It is a small single-node stack (Docker), a synthetic data generator,
seven example queries and a raw-versus-rollup benchmark, all talking to ClickHouse over HTTP
with the Python standard library.

Study notes live in `experiments/clickhouse-podcast-analytics/notes/clickhouse-design-notes.md`.

## 2. Quick start

Prerequisites: Docker, Python 3 (stdlib only, no installs) and make. Ports 8123 and 9000 on
127.0.0.1 must be free. The image is pinned to `clickhouse/clickhouse-server:26.8.39.19`, a
patch release of the 26.8 LTS line.

```
make all        # up, generate, queries, bench
make up         # start the server; schema/ is loaded on first start
make generate   # truncate and reload synthetic data (idempotent)
make queries    # run every queries/*.sql
make bench      # raw versus rollup benchmark
python3 scripts/bench.py --optimize-rollups   # same, after fully merging the rollups
make down       # stop and delete the container and its volume
```

Timings from a clean `make all` on 2026-11-17 (image already pulled):

| step | time |
|---|---|
| `make up` (start, schema loaded, healthy) | about 6 s |
| `make generate` (about 5.3M rows, 100,000 per INSERT) | about 22 s |
| `make queries` (7 files) | about 1 s |
| `make bench` | about 11 s |
| total | about 40 s |

## 3. Layout

```
experiments/clickhouse-podcast-analytics/
  docker-compose.yml   one clickhouse service, named volume, healthcheck, schema/ mounted read-only
  Makefile             up, generate, queries, bench, all, down
  schema/01_tables.sql database, dimensions, dictionary, fact tables
  schema/02_rollups.sql rollup tables and materialized views
  scripts/ch.py        tiny HTTP helper: query, insert, parsed X-ClickHouse-Summary header
  scripts/generate.py  deterministic synthetic data generator (--seed, --scale, --end-date)
  scripts/bench.py     raw table versus rollup benchmark
  queries/NN_name.sql  seven example queries
  notes/               study notes
```

## 4. Data model

Database `podcast`.

| table | engine | ORDER BY | partition | purpose |
|---|---|---|---|---|
| podcasts | MergeTree | podcast_id | none | dimension |
| episodes | MergeTree | podcast_id, episode_id | none | dimension |
| brands | MergeTree | brand_id | none | dimension, source of `brands_dict` |
| campaigns | MergeTree | brand_id, campaign_id | none | brand ad windows |
| brands_dict | dictionary, FLAT | brand_id | n/a | name/industry lookup via dictGet |
| transcript_segments | MergeTree, TTL 2 years | podcast_id, episode_id, segment_idx | toYYYYMM(published_at) | text search (text index) |
| brand_mentions | MergeTree, projection `by_podcast` | brand_id, mentioned_at, podcast_id | toYYYYMM(mentioned_at) | raw detected mentions |
| downloads | ReplacingMergeTree(ingested_at), PRIMARY KEY (podcast_id, episode_id) | podcast_id, episode_id, download_id | toYYYYMM(downloaded_at) | raw downloads, dedup on id |
| brand_mentions_daily | AggregatingMergeTree | day, brand_id | none | rollup fed by `brand_mentions_daily_mv` |
| downloads_daily | AggregatingMergeTree | day, region, device | none | rollup fed by `downloads_daily_mv` |

## 5. Design decisions and tradeoffs

### Brand-first sorting key on brand_mentions
- Decision: ORDER BY (brand_id, mentioned_at, podcast_id).
- Why: the main drill-down is one brand over a date range, so the brand leads and the date range is a contiguous slice.
- Tradeoff / revisit: podcast-first or time-only scans do not benefit (the projection and rollup cover those). With many more brands a very skewed brand could make large granule ranges; I would look at the key again.

### Monthly partitions
- Decision: PARTITION BY toYYYYMM on the time column of each fact table.
- Why: cheap range pruning (min-max and partition) and whole-month drops for TTL.
- Tradeoff / revisit: this dataset covers 7 calendar months, so each insert touches several partitions and creates several small parts. Too-fine partitioning at scale means too many parts.

### LowCardinality and narrow integer types
- Decision: LowCardinality(String) for publisher, category, language, industry, region, device, mention_type, detector_version; UInt32 ids where 4 billion is plenty, UInt64 for episodes.
- Why: smaller on disk, faster scans and GROUP BY.
- Tradeoff / revisit: the LowCardinality docs say it mostly helps below about 10,000 distinct values and can do worse than plain types above about 100,000 (https://clickhouse.com/docs/sql-reference/data-types/lowcardinality). Narrow types make later widening a migration.

### AggregatingMergeTree rollup via materialized view, and why queries re-aggregate
- Decision: `brand_mentions_daily` and `downloads_daily` are filled by materialized views that fire on every insert block.
- Why: each insert block becomes its own partial row per (day, brand); merges combine them later and only eventually. A query reading before a merge sees several partial rows per key, so it must use sum(...) / uniqMerge(...) with GROUP BY.
- Tradeoff / revisit: the view only sees new inserts. History needs a backfill, and a changed view definition does not rewrite old rows.

### Storing uniq states instead of counts
- Decision: `episodes`, `podcasts`, `downloads` and `listener_episodes` are AggregateFunction(uniq, ...) states.
- Why: distinct counts cannot be added across days or brands; states can be merged into any coarser grain (month, all time).
- Tradeoff / revisit: states are larger than integers, and merging them was slower than scanning the raw table in my runs (benchmark pairs d and e). uniq is also approximate. Against 2,999,999 exact download ids, merging every state into one gave 2,988,038 (about 0.4% low), summing per-day results gave 2,999,993, and summing per (day, region, device) gave 2,999,999. Small states were exact here; the big merged one was not.

### by_podcast projection versus a second table
- Decision: a PROJECTION by_podcast (SELECT * ORDER BY podcast_id, mentioned_at) inside brand_mentions.
- Why: podcast-first lookups get a second sort order that the optimizer picks automatically and that stays consistent with the base data.
- Tradeoff / revisit: the data is stored twice (36.9 MiB projection next to 41.1 MiB base here) and each insert does extra work. A separate table would allow a different engine or TTL but needs its own feeding logic.

### ReplacingMergeTree for downloads, PRIMARY KEY as a prefix of ORDER BY, FINAL
- Decision: ORDER BY (podcast_id, episode_id, download_id) is the row identity; PRIMARY KEY (podcast_id, episode_id) is a shorter prefix; ingested_at is the version.
- Why: at-least-once delivery produces duplicate rows with the same id. The prefix keeps the in-memory index small while the full key defines what counts as the same row.
- Tradeoff / revisit: deduplication happens only when parts merge, so until then duplicates are visible. FINAL gives correct results but does the merge at read time, which is extra work on every query. In query 04 the raw count was 512,012 against 507,054 after FINAL for one month.

### Why the downloads rollup uses a distinct-count state
- Decision: `downloads_daily.downloads` is uniqState(download_id), not a count.
- Why: a materialized view sees every inserted block, including redelivered duplicates the ReplacingMergeTree removes later. A plain count would include them forever; a distinct state counts each id once.
- Tradeoff / revisit: the state keeps one hash per download id, so it is not small (22.2 MiB for 21,565 rows once merged, against 105.4 MiB for the raw table), and it was slower than the raw table in benchmark pair e. If the dedup key were not unique per event, this would not work.

### Token skip index (text index) and its limits
- Decision: `INDEX text_tokens text TYPE text(tokenizer = splitByNonAlpha)` on transcript_segments.text, queried with hasToken.
- Why: the text index is generally available since 26.2 (verified on 26.8.39.19, no experimental setting needed). The MergeTree docs say tokenbf_v1 is no longer recommended for full-text search and label tokenbf_v1/ngrambf_v1 "(Deprecated)"; the bloom-filter indexes still exist.
- Tradeoff / revisit: the index works on whole tokens, so substring searches need other functions. Its granularity is the whole part ("GRANULARITY 100000000" in SHOW CREATE TABLE), so it can rule out a part where the token never occurs, but a token present in every part skips nothing at the part level. It also adds storage and insert cost, and tokens are case-sensitive here: `Taworiji` matches 3,091 segments and `taworiji` matches none.

### TTL on transcripts
- Decision: TTL published_at + INTERVAL 2 YEAR.
- Why: transcripts are the bulkiest text and the least needed after a while.
- Tradeoff / revisit: nothing here is old enough to expire, so I have not seen it run. Row-level TTL rewrites parts; with monthly partitions, whole-partition drops could be cheaper.

### Dictionary versus JOIN for brand names
- Decision: `brands_dict` (FLAT layout, 300-600 s lifetime) used with dictGet.
- Why: 200 brands with small dense ids is the ideal case; lookups are array indexing and the query has no join.
- Tradeoff / revisit: renamed brands appear only after the next reload, and FLAT needs dense ids. For wide or sparse keys, a hashed layout or a regular JOIN.

### Plain MergeTree for brand_mentions, and what a detector re-run would need
- Decision: plain MergeTree, append only, with detector_version stored per row.
- Why: mentions are events; nothing is updated.
- Tradeoff / revisit: re-running a detector would produce a second set of mentions for the same segments. It needs either a delete or drop of the old version by partition, or a ReplacingMergeTree keyed on (episode, segment, detector). The rollup would double count because its view cannot see deletes, so it would need a rebuild.

### Single node only
- Decision: one server, no replication, no sharding, no Keeper.
- Why: the point is table design and query behaviour, which do not need a cluster.
- Tradeoff / revisit: Replicated* engines, distributed tables and shard keys change several of the choices above (dedup, projections, rollups); that is a separate experiment.

## 6. Example queries

- `queries/01_top_brands_weekly.sql` top 10 brands per week from the rollup, names via dictGet.
- `queries/02_share_of_voice.sql` each brand's share of all mentions and of its industry per week, plus a sums-to-100 check.
- `queries/03_campaign_windows.sql` mentions inside each campaign window and daily average inside versus outside.
- `queries/04_download_dedup.sql` one month of downloads: raw, FINAL, uniqExact(download_id), one per listener per episode per day.
- `queries/05_downloads_region_device.sql` downloads by region and device for the top 5 podcasts.
- `queries/06_transcript_search.sql` hasToken search plus EXPLAIN indexes = 1 for the text index.
- `queries/07_brand_drilldown.sql` one brand by day and type; podcast-first lookup with EXPLAIN showing the projection.

## 7. Benchmark

`scripts/bench.py` asks the same five questions from the raw table and from the rollup. Each
query runs once as a warm-up and then 7 timed runs. It reports the median and minimum
client-side wall-clock milliseconds and the server's read_rows and read_bytes from the
X-ClickHouse-Summary header, with the query cache switched off. It compares both answers
line by line and prints MATCH or DIFF per pair, and it waits for background merges to settle
before timing. With `--optimize-rollups` it first runs `OPTIMIZE TABLE ... FINAL` on both
rollup tables, so the same questions can be timed against fully merged rollups.

Both runs below are from 2026-11-17 on ClickHouse 26.8.39.19, Docker Desktop on a laptop
(12 CPUs, 8 GB VM), back to back on the same data: brand_mentions 2,000,000 rows and
downloads 3,029,998 rows (including 29,999 redelivered duplicates). They are from one small
local run and do not predict behaviour at production size.

Run 1, rollups as the inserts left them (`make bench`): brand_mentions_daily 95,661 rows in
4 parts, downloads_daily 87,720 rows in 5 parts.

| pair | raw median ms | raw min ms | raw read_rows | raw read_bytes | rollup median ms | rollup min ms | rollup read_rows | rollup read_bytes | result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| a. one brand, mentions per day, 90 days | 9.3 | 8.4 | 253,593 | 1.9 MiB | 6.4 | 5.4 | 54,701 | 747.9 KiB | MATCH |
| b. top 10 brands per week, all data | 9.7 | 8.6 | 2,000,000 | 15.3 MiB | 5.1 | 4.5 | 95,661 | 1.3 MiB | MATCH |
| c. share of voice per week | 9.1 | 8.5 | 2,000,000 | 15.3 MiB | 5.1 | 4.7 | 95,661 | 1.3 MiB | MATCH |
| d. distinct episodes per brand per month | 26.5 | 26.0 | 2,000,000 | 30.5 MiB | 51.5 | 48.6 | 95,661 | 8.6 MiB | MATCH |
| e. deduplicated downloads per region per day | 54.3 | 52.5 | 3,029,998 | 60.7 MiB | 73.8 | 70.1 | 87,720 | 7.6 MiB | MATCH |

Run 2, rollups fully merged (`python3 scripts/bench.py --optimize-rollups`):
brand_mentions_daily 35,986 rows, downloads_daily 21,565 rows, one part each.

| pair | raw median ms | raw min ms | raw read_rows | raw read_bytes | rollup median ms | rollup min ms | rollup read_rows | rollup read_bytes | result |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| a. one brand, mentions per day, 90 days | 8.5 | 6.7 | 253,593 | 1.9 MiB | 3.2 | 2.3 | 19,602 | 268.0 KiB | MATCH |
| b. top 10 brands per week, all data | 8.9 | 8.0 | 2,000,000 | 15.3 MiB | 3.4 | 3.1 | 35,986 | 492.0 KiB | MATCH |
| c. share of voice per week | 8.3 | 7.9 | 2,000,000 | 15.3 MiB | 4.4 | 3.8 | 35,986 | 492.0 KiB | MATCH |
| d. distinct episodes per brand per month | 26.5 | 25.9 | 2,000,000 | 30.5 MiB | 52.3 | 51.3 | 35,986 | 3.2 MiB | MATCH |
| e. deduplicated downloads per region per day | 53.1 | 52.5 | 3,029,998 | 60.7 MiB | 90.7 | 90.1 | 21,565 | 1.9 MiB | MATCH |

What I take from it:

- The sum-based rollups (a to c) were faster in both runs and read far fewer rows: 35,986
  against 2,000,000 once merged.
- Before merging, the mentions rollup held about 2.7 times as many rows (95,661 against
  35,986): one partial row per insert block per key. It still gave the same answers, which
  is why every rollup query re-aggregates with GROUP BY.
- The distinct-count rollups (d and e) were slower than the raw table in both runs, although
  they read far fewer rows. Merging the rollup did not help: pair e went from 73.8 ms to
  90.7 ms.
- The states are not small, and that is measured. After merging, each `downloads` state
  holds 139 distinct ids on average (559 bytes serialized on average, 23,711 bytes for the
  largest), and 21,565 states times 139 is about 3 million. So the rollup still carries one
  hash per download: every download id is unique and there is nothing to collapse.
  downloads_daily takes 22.2 MiB on disk for 21,565 rows. Pair d has the same shape, with 42
  distinct episodes per state on average across 35,986 states.
- So a distinct-count state pays off when many raw rows share a value inside one key (a
  listener who downloads often), and not when the counted value is unique per row. At this
  grain the downloads rollup bought correct counts under redelivery, not speed.
- read_bytes does not seem to include the size of aggregate states: pair e reports 1.9 MiB
  read from a table whose single part is 22.2 MiB. That is my reading of these numbers; I
  did not confirm it in the docs. For pairs d and e, wall-clock is the column to trust.

## 8. Limits and next things to try

- Everything is synthetic and small. At 2 to 3 million rows every query answers in tens of
  milliseconds, so these runs show the direction of a difference, not its size on real data.
- The raw tables had not merged down when the benchmark ran (30 parts for brand_mentions, 34
  for downloads), and the Docker VM's page cache was warm.
- Try: a bounded sketch state (uniqCombined or uniqHLL12) for the downloads rollup, and a
  plain count over already-deduplicated rows fed by a refreshable materialized view on
  `downloads FINAL`; rerun pair e against both.
- Try: a bigger `--scale`, to see whether pairs d and e change direction.
- Try: SummingMergeTree for the sum-only columns, and a hashed dictionary layout.
- Try: a backfill script for the materialized views, and a detector re-run as a partition swap.
