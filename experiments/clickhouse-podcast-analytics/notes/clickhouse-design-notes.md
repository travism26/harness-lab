# ClickHouse design notes

Notes from exploring ClickHouse for fun, using podcast ad measurement as the running example: which podcasts mention which brands, near-real-time transcript and download data, and campaign attribution. The runnable companion project is described in `experiments/clickhouse-podcast-analytics/README.md`.

How to read these notes:

- Every claim about ClickHouse links to the official docs page it came from (all under https://clickhouse.com/docs). Sentences marked as my inference, judgment or synthesis are mine, not the docs'.
- The only numbers are defaults and recommendations the docs state. There are no benchmarks here; measured numbers from my own small run are in the README.
- The docs were read on 2026-11-17 and describe current releases, so version qualifiers ("since 26.2") are quoted as the docs give them. Thirty of the most error-prone claims (defaults, version numbers, feature status) were re-checked against the raw page text.
- SQL snippets are illustrative and use made-up table names; the schema that actually runs is in `experiments/clickhouse-podcast-analytics/schema/01_tables.sql` and `experiments/clickhouse-podcast-analytics/schema/02_rollups.sql`.

## Contents

1. Storage fundamentals
2. Ingestion patterns
3. Materialized views and projections
4. Updates and deletes
5. Joins and dictionaries
6. Replication, sharding and Distributed tables
7. When not to use ClickHouse
8. Worked design scenarios

## 1. Storage fundamentals

Running example: podcast ad measurement (`brand_mentions`, `downloads`, `transcript_segments`). SQL below is illustrative, not copied from the docs.

### Columnar storage

- A columnar database stores the data of each column independently, and ClickHouse is the docs' typical example ([Why is ClickHouse a columnar database](https://clickhouse.com/docs/faq/general/columnar-database)).
- Queries read from disk only the columns they use. That allows many columns in a table without paying for unused ones at read time ([columnar FAQ](https://clickhouse.com/docs/faq/general/columnar-database)).
- The FAQ lists three advantages: queries touching a few columns out of many, aggregations over large volumes, and column-wise compression ([columnar FAQ](https://clickhouse.com/docs/faq/general/columnar-database)).
- The trade-off, as the FAQ states it: operations that affect whole rows become proportionally more expensive. A row-oriented OLTP database reads whole rows because data is stored in rows ([columnar FAQ](https://clickhouse.com/docs/faq/general/columnar-database)).
- So one-row-at-a-time access is not the strength: the FAQ frames whole-row operations as the costly case ([columnar FAQ](https://clickhouse.com/docs/faq/general/columnar-database)).

#### Compression and codecs

- ClickHouse writes values in column order, and sorting puts identical values next to each other, which gives compression algorithms patterns to exploit ([Compression in ClickHouse](https://clickhouse.com/docs/data-compression/compression-in-clickhouse)).
- Compression is affected by three principal factors: the ordering key, data types and codecs ([compression](https://clickhouse.com/docs/data-compression/compression-in-clickhouse)).
- Self-managed default: `LZ4` for parts smaller than 100 MiB and `ZSTD(3)` for larger parts. The same page says ClickHouse Cloud uses `ZSTD` with a default level of 1 ([compression](https://clickhouse.com/docs/data-compression/compression-in-clickhouse)).
- Codec guidance from the same page:
  - `Delta` works well on monotonic sequences or small deltas between consecutive values; `ZSTD` is effective on delta data.
  - `DoubleDelta` is worth testing when `Delta` alone is not enough.
  - `Gorilla` can be effective on floating-point gauge readings.
  - `T64` can be effective on sparse data or when the range in a block is small.
- Illustrative column-level codecs:

```sql
-- illustrative
CREATE TABLE downloads
(
    downloaded_at DateTime CODEC(Delta, ZSTD),
    episode_id    UInt64,
    listener_id   UInt64,
    bytes_served  UInt32
)
ENGINE = MergeTree
ORDER BY (episode_id, downloaded_at);
```

**Design takeaway:** `brand_mentions` queries like "mentions per brand per week" touch two or three columns out of many, which is the access pattern columnar storage serves; fetching one full transcript row by id is not the pattern to design around.

### The MergeTree family

#### Plain MergeTree

- Each insert creates a table part, and a background process merges parts ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Each part is sorted by the primary key. Parts from different partitions are never merged together ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Merging does not guarantee that all rows with the same primary key end up in one data part ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Guarantee you do NOT get: uniqueness. The primary key is not a unique constraint; same-key rows can sit in different parts.

**Design takeaway:** `downloads` is an append-only event stream, so plain MergeTree is the default; I only reach for a special engine when rows need to be replaced, summed or cancelled.

#### ReplacingMergeTree

- Merge behaviour: removes older rows with the same sorting key. Without a `ver` column the last inserted row wins; with `ver` (type `UInt*`, `Date`, `DateTime` or `DateTime64`) the row with the biggest `ver` wins ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- `is_deleted` marks whether a row represents state or a delete. It can only be enabled when `ver` is used, and by default the last row for a key is kept even when it is a delete row ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- Deduplication happens only during a merge, which occurs in the background at an unknown time, so it cannot be planned ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- Because parts from different partitions are never merged, duplicates across partitions are not collapsed ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree), [Partitions](https://clickhouse.com/docs/partitions)). Practical consequence: keep the partition key stable for a given sorting key. The ReplacingMergeTree page itself does not state this scope rule.
- NOT guaranteed: deduplication. Update and delete rows still count in queries until merged ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- Querying correctly: combine merges with query-time deduplication using `FINAL`. Manual `OPTIMIZE` is possible but the docs say not to count on it because it reads and writes a lot of data ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).

**Design takeaway:** `episodes` metadata (title edits, takedowns) fits ReplacingMergeTree with `updated_at` as `ver`; reads that must be exact use `FINAL`.

#### SummingMergeTree

- Merge behaviour: rows with the same sorting key are replaced by one row holding summed numeric values. Rows whose summed values are all zero are deleted during a merge ([SummingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/summingmergetree)).
- `columns` is optional. Without it, all numeric columns not in the sorting key are summed. Summed columns must be numeric and not in the partition or sorting key ([SummingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/summingmergetree)).
- Columns that are neither key nor summed get an arbitrary value from the existing rows ([SummingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/summingmergetree)).
- NOT guaranteed: complete summation. Merges are periodic, so a query can see unmerged rows ([SummingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/summingmergetree)).
- Querying correctly: use `sum()` with `GROUP BY`. `FINAL` also sums rows but does not delete all-zero rows ([SummingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/summingmergetree)).

```sql
-- illustrative
CREATE TABLE downloads_daily
(
    day Date,
    episode_id UInt64,
    downloads  UInt64
)
ENGINE = SummingMergeTree
ORDER BY (episode_id, day);

SELECT episode_id, day, sum(downloads)
FROM downloads_daily
GROUP BY episode_id, day;
```

**Design takeaway:** a per-episode per-day download counter is the natural SummingMergeTree case; I still write `sum(...) GROUP BY` and treat merged rows as an optimization, not a contract.

#### AggregatingMergeTree

- The engine processes columns of type `AggregateFunction` and `SimpleAggregateFunction` ([AggregatingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/aggregatingmergetree)).
- Merge behaviour: rows with the same sorting key collapse into one row (within a data part) that stores a combination of aggregate function states ([AggregatingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/aggregatingmergetree)).
- Insert with `-State` functions, read with the same functions using the `-Merge` suffix (`sumMerge`, `uniqMerge`) ([AggregatingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/aggregatingmergetree)).
- The docs describe use for incremental aggregation, including aggregated materialized views, which shifts aggregation cost from insert time to merge time ([AggregatingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/aggregatingmergetree)).
- Because the single row is per data part, reads still need the `-Merge` function plus `GROUP BY`; unmerged parts can hold several rows for one key.

```sql
-- illustrative
CREATE TABLE listeners_by_brand
(
    day   Date,
    brand String,
    listeners AggregateFunction(uniq, UInt64)
)
ENGINE = AggregatingMergeTree
ORDER BY (brand, day);

-- insert side: uniqState(listener_id)
SELECT brand, day, uniqMerge(listeners)
FROM listeners_by_brand
GROUP BY brand, day;
```

**Design takeaway:** "unique listeners reached per brand per day" cannot be summed across days or parts, so it needs `uniqState` / `uniqMerge`, not SummingMergeTree.

#### CollapsingMergeTree

- A `Sign` column (Int8): `1` is a state row, `-1` is a cancel row ([CollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/collapsingmergetree)).
- Merge behaviour: pairs of rows are removed when all sorting-key fields are equal except `Sign`; rows without an opposite partner stay ([CollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/collapsingmergetree)).
- Collapsing happens only during background merges at unpredictable times, so uncollapsed rows remain until then ([CollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/collapsingmergetree)).
- NOT guaranteed: sensible results from inconsistent history. Results depend strongly on the consistency of the change history, and the docs warn about unpredictable results for inconsistent input ([CollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/collapsingmergetree)).
- Querying correctly: use `sum(Sign * x)` with `HAVING sum(Sign) > 0` instead of `sum(x)`, and `sum(Sign)` instead of `count()`. `min` and `max` cannot be computed correctly. `FINAL` forces collapsing but is slower on large scans ([CollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/collapsingmergetree)).

#### VersionedCollapsingMergeTree

- Same purpose as CollapsingMergeTree with a different algorithm, taking `(sign, version)` ([VersionedCollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/versionedcollapsingmergetree)).
- It allows inserts in any order and from multiple threads, whereas CollapsingMergeTree allows only strictly consecutive insertion ([VersionedCollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/versionedcollapsingmergetree)).
- If `version` is not in the key, ClickHouse adds it as the last key field. Rows with the same key and version but opposite `Sign` collapse regardless of row order ([VersionedCollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/versionedcollapsingmergetree)).
- Querying correctly: same sign-aware aggregation (`sum(Sign * x)`, `HAVING sum(Sign) > 0`, group by key and version). `min`/`max` do not work; `FINAL` works but the docs say not to use it on large tables ([VersionedCollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/versionedcollapsingmergetree)).
- When order matters: if the stream of state and cancel rows can arrive out of order (several consumers), prefer the versioned variant.

**Design takeaway:** if campaign spend rows get corrected by cancel-and-reinsert from several ingest workers, VersionedCollapsingMergeTree tolerates the out-of-order arrival; plain Collapsing does not.

### ORDER BY (sorting key) vs PRIMARY KEY

- `ORDER BY` defines the sorting key. If `PRIMARY KEY` is not specified, ClickHouse uses the sorting key as the primary key; specifying a sorting key implicitly specifies a primary key ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- If both are given, the primary key expression tuple must be a prefix of the sorting key tuple ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- The primary key determines the sparse index, while the sorting key determines on-disk row order; the guide uses a longer sorting key than primary key to improve compression ([Sparse primary indexes](https://clickhouse.com/docs/guides/best-practices/sparse-primary-indexes)).
- A long primary key negatively affects insert performance and memory consumption. `Nullable` key expressions are strongly discouraged ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Choosing column order, from the docs:
  - Prioritize columns frequently used in filters, especially those that exclude many rows; correlated columns help compression; the key determines physical order, so it directly impacts compression ([Choosing a primary key](https://clickhouse.com/docs/best-practices/choosing-a-primary-key)).
  - 4-5 key columns are typically sufficient, and the ordering key must be defined at table creation and cannot be added later ([Choosing a primary key](https://clickhouse.com/docs/best-practices/choosing-a-primary-key)).
  - Cardinality: the sparse-index guide advises ordering key columns by cardinality in ascending order, which helps filtering on secondary key columns and compression ([Sparse primary indexes](https://clickhouse.com/docs/guides/best-practices/sparse-primary-indexes)). The best-practices page gives no general cardinality rule, only an example with a low-cardinality first column ([Choosing a primary key](https://clickhouse.com/docs/best-practices/choosing-a-primary-key)).

```sql
-- illustrative: sorting key longer than primary key
CREATE TABLE brand_mentions
(
    brand String, podcast_id UInt32, episode_id UInt64,
    mentioned_at DateTime, segment_id UInt64
)
ENGINE = MergeTree
PRIMARY KEY (brand, podcast_id)
ORDER BY (brand, podcast_id, mentioned_at);
```

**Design takeaway:** for "which podcasts mention brand X", lead the key with `brand` then `podcast_id`; adding `mentioned_at` to the sorting key only (not the primary key) keeps the in-memory index small.

### Partitioning

- `PARTITION BY` is optional. The docs call partitioning primarily a data management technique, not a query optimization tool ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree), [Choosing a partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)).
- It groups data parts into logical units; partitions can be dropped, moved or archived in a single metadata operation, and it works with TTL and tiered storage ([Partitions](https://clickhouse.com/docs/partitions), [Choosing a partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)).
- Monthly partitioning uses `toYYYYMM(date_column)`; do not partition by client identifiers or names, make them the first `ORDER BY` column instead ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Pruning: MinMax indexes on the partition key let ClickHouse skip whole partitions, then the primary index skips granules ([Partitions](https://clickhouse.com/docs/partitions)). It only helps queries that filter on the partition key; querying across all partitions can be slower than a non-partitioned table ([Partitions](https://clickhouse.com/docs/partitions), [Choosing a partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)).
- Warnings:
  - "You should never use too granular partitioning" ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
  - Merges happen only within a partition; parts spread across thousands of partitions never become merge candidates, which can trigger the "Too many parts" error ([Partitions](https://clickhouse.com/docs/partitions)).
  - Cardinality guidance differs by page: under 1000..10000 on the [Partitions](https://clickhouse.com/docs/partitions) page, fewer than 100 - 1,000 distinct values on [Choosing a partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key).

```sql
-- illustrative
PARTITION BY toYYYYMM(downloaded_at)
```

**Design takeaway:** partition `downloads` by month so old months can be dropped or moved wholesale; never by `podcast_id` or `episode_id`.

### Granules and the sparse primary index

- A granule is the smallest indivisible data set ClickHouse reads when selecting data; it never splits a row ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Rows per granule lie in `[1, index_granularity]`; the default `index_granularity` is 8192 ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Each granule's first row has a mark holding its primary key value; marks live in an index file, and ClickHouse keeps marks for each column too ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- The index is sparse (one entry per granule, not per row), so it can stay in RAM even for very large tables; reading one key range can read up to `index_granularity * 2` extra rows per data block ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Selecting granules: when the filter is on the first key column, ClickHouse runs binary search over the index marks ([Sparse primary indexes](https://clickhouse.com/docs/guides/best-practices/sparse-primary-indexes)).
- Filter on a later column only: ClickHouse uses the generic exclusion search, which the guide says is most effective when the predecessor key column has lower cardinality; if the predecessor has similarly high cardinality, few granules are skipped ([Sparse primary indexes](https://clickhouse.com/docs/guides/best-practices/sparse-primary-indexes)).
- Queries can use the index for equality, `IN`, and `LIKE` with a fixed prefix on key columns; filtering only on a non-prefix column can read much more data ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).

**Design takeaway:** a query for `podcast_id = 42` on a key `(brand, podcast_id, ...)` falls into generic exclusion; it works well only because `brand` has comparatively few distinct values.

### Data skipping indexes

- Declared as `INDEX name expr TYPE type(...) GRANULARITY n`. `GRANULARITY` can be omitted; default is 1 ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)). Each indexed block consists of GRANULARITY granules (example: 4 x 8192 = 32768 rows) ([Skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)).
- Types:
  - `minmax`: min and max of an expression per block; no parameters; ideal for columns loosely sorted by value ([Skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)).
  - `set(max_rows)`: stores unique values per block, `0` means unlimited; the index is empty if a block exceeds the size, so it is less effective with many unique values per block ([Skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)).
  - `bloom_filter([false_positive_rate])`: default rate 0.025; suits testing many discrete values, including array elements and map keys or values ([Skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes), [MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
  - `tokenbf_v1(size, hashes, seed)` and `ngrambf_v1`: both marked deprecated; `tokenbf_v1` works on String, FixedString and Map ([Skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes), [MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
  - `text`: an inverted index for full-text search, recommended over the deprecated token/ngram indexes. The MergeTree page says it reached general availability in ClickHouse 26.2 ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)); the skipping-indexes page calls it the recommended choice for full-text search but does not state a maturity label ([Skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)).
- When they help: a strong correlation between the primary key and the indexed column; rare values in high-cardinality columns (error codes) where many blocks lack the value ([Skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)).
- When they do not: if a value occurs even once in a block the whole block is read; with no correlation most blocks still match. The page suggests first considering primary key changes, projections or materialized views ([Skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)).
- Bloom-filter indexes can return false positives, so they cannot optimize queries where the predicate is expected to be false, such as `NOT s LIKE '%test%'` ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Indexes apply only to newly inserted data by default; use `ALTER TABLE ... MATERIALIZE INDEX` for existing data ([Skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)).

```sql
-- illustrative
ALTER TABLE brand_mentions
    ADD INDEX sentiment_idx sentiment TYPE set(100) GRANULARITY 4;
ALTER TABLE brand_mentions MATERIALIZE INDEX sentiment_idx;
```

**Design takeaway:** searching `transcript_segments` for brand words is the text-index case; a skipping index on `listener_id` for random lookups is the poor-fit case because values are scattered across blocks.

### TTL

- TTL can be set on columns and tables; expressions must yield `Date`, `Date32`, `DateTime` or `DateTime64` ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Row TTL: defined at table level; when rows expire, ClickHouse deletes them. `DELETE` is the default action and can use a `WHERE` clause to delete only some expired rows; no more than one `DELETE` rule ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree), [TTL guide](https://clickhouse.com/docs/guides/developer/ttl)).
- Column TTL: expired values are replaced with the column type's default; if all values in a part expire, the column is removed from that part. It cannot be used on key columns ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- Moves: `TO DISK 'xxx'` / `TO VOLUME 'xxx'`, and `RECOMPRESS codec`. For moves and recompression, all rows of a part must satisfy the TTL expression ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)). The TTL guide flags its hot/warm/cold `TO DISK` / `TO VOLUME` lesson as not supported in ClickHouse Cloud and says you do not need to move old data around there ([TTL guide](https://clickhouse.com/docs/guides/developer/ttl)).
- `GROUP BY` rollup: aggregates expired rows; the `GROUP BY` expression must be a prefix of the primary key; columns not grouped or `SET` take an arbitrary value from the group ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- When applied: TTL is evaluated during background merges, not at insert time. Non-deterministic functions like `now()` are re-evaluated on every merge ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)). Removal is not immediate; by default TTL rules run at least every 4 hours, controlled by `merge_with_ttl_timeout` ([TTL guide](https://clickhouse.com/docs/guides/developer/ttl)). Expired rows may be visible between merges ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)).
- After changing a rule, `ALTER TABLE ... MATERIALIZE TTL` forces it to apply ([TTL guide](https://clickhouse.com/docs/guides/developer/ttl)).

```sql
-- illustrative: roll raw downloads up to daily counts after 30 days
TTL downloaded_at + INTERVAL 30 DAY
    GROUP BY episode_id, toStartOfDay(downloaded_at)
    SET bytes_served = sum(bytes_served)
```

**Design takeaway:** keep raw `downloads` for a bounded window, roll old rows into daily aggregates with TTL `GROUP BY`, and never rely on TTL for exact-time deletion.

## 2. Ingestion patterns

Running example: `brand_mentions` (one row per brand mention found in a transcript segment), `downloads` (one row per episode download event), `brand_mentions_daily` (rollup). All SQL below is illustrative.

### 2.1 Every insert is a part

- Table data is stored as a collection of immutable data parts, and a new part is created whenever a set of rows is inserted ([Parts](https://clickhouse.com/docs/parts)).
- On insert the server sorts the rows by the sorting key, splits them into columns, compresses them and writes them to a new directory ([Parts](https://clickhouse.com/docs/parts)).
- A background job combines smaller parts into larger ones; each merge increments the part's level, and level 0 means a part that has not been merged yet ([Parts](https://clickhouse.com/docs/parts)).
- An insert that spans several partitions creates one part per partition ([Too many parts](https://clickhouse.com/docs/knowledgebase/exception-too-many-parts)).
- Fewer, larger inserts reduce the number of parts written and the merge load ([Bulk inserts](https://clickhouse.com/docs/optimize/bulk-inserts)).

#### The "Too many parts" error

- `parts_to_delay_insert` defaults to 1000: when a partition's active part count exceeds it, ClickHouse deliberately slows each insert so merges can catch up ([parts_to_*](https://clickhouse.com/docs/reference/settings/merge-tree-settings/parts-to)).
- `parts_to_throw_insert` defaults to 3000 (it was 300 before version 23.6): past it the insert fails with `Too many parts (N). Merges are processing significantly slower than inserts` ([parts_to_*](https://clickhouse.com/docs/reference/settings/merge-tree-settings/parts-to)).
- `max_parts_in_total` is the table-wide equivalent of the per-partition limit ([Too many parts](https://clickhouse.com/docs/knowledgebase/exception-too-many-parts)). I could not find its default on a docs page I fetched, so I do not quote one.
- Causes the docs list: frequent small synchronous inserts, a high-cardinality partitioning key, inserts touching many partitions, and merges falling behind because of slow storage, low disk space or resource contention ([Too many parts](https://clickhouse.com/docs/knowledgebase/exception-too-many-parts)).
- The docs say raising `parts_to_throw_insert` or `max_parts_in_total` only delays the error and adds filesystem, metadata and query overhead; raising the first can also hurt SELECT performance ([Too many parts](https://clickhouse.com/docs/knowledgebase/exception-too-many-parts), [parts_to_*](https://clickhouse.com/docs/reference/settings/merge-tree-settings/parts-to)).
- Merges happen only within a partition, so the docs advise a low-cardinality partitioning key and not values such as user or request IDs ([Too many parts](https://clickhouse.com/docs/knowledgebase/exception-too-many-parts)).

Illustrative monitoring query (the docs point at `system.parts` for active part counts):

```sql
-- illustrative
SELECT partition, count() AS active_parts
FROM system.parts
WHERE database = 'podcasts' AND table = 'brand_mentions' AND active
GROUP BY partition
ORDER BY active_parts DESC;
```

**Design takeaway:** partition `brand_mentions` coarsely (for example by month) and never by podcast or episode id; a transcript worker that inserts one row per segment will hit the part limits long before it hits any storage limit.

### 2.2 Batching: the documented numbers

- Insert at least 1,000 rows per batch, ideally 10,000 to 100,000 ([Bulk inserts](https://clickhouse.com/docs/optimize/bulk-inserts)).
- Keep to roughly one insert query per second regardless of batch size; asynchronous inserts can exceed this rate ([Bulk inserts](https://clickhouse.com/docs/optimize/bulk-inserts)).
- The Parts page gives "20,000 rows at once" as an example of bulk insertion that reduces the initial part count and merge overhead ([Parts](https://clickhouse.com/docs/parts)).
- The docs state that for a synchronous insert strategy to be effective, client-side batching is required; if you cannot batch on the client, use asynchronous inserts, which move batching to the server ([Bulk inserts](https://clickhouse.com/docs/optimize/bulk-inserts)).
- The "too many parts" guidance repeats the same figures: at least 1,000 rows, ideally 10,000 to 100,000, about one synchronous insert per second ([Too many parts](https://clickhouse.com/docs/knowledgebase/exception-too-many-parts)).

**Design takeaway:** the `downloads` event stream should be buffered in the ingest service and flushed as one batch per second or per tens of thousands of rows, not forwarded one event per HTTP request.

### 2.3 Asynchronous inserts

- `async_insert` buffers inserts on the server and flushes them later. It is on by default since 26.2 (off before that; the settings reference lists "26.2 | 1 | Enable async inserts by default" in its version history, and the deduplication guide says "enabled by default since version 26.2"). It can still be set per user (`ALTER USER ... SETTINGS async_insert = 1`), per query, or in client connection parameters ([Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts), [settings reference](https://clickhouse.com/docs/reference/settings/session-settings/async-insert), [Deduplicating inserts on retries](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)). On older versions, check `system.settings`.
- With async inserts ClickHouse buffers rows from several INSERTs and creates a part only when the buffer passes a threshold or a timeout expires ([Parts](https://clickhouse.com/docs/parts)).

#### wait_for_async_insert and durability

- `wait_for_async_insert = 1` (default): the server acknowledges only after the data is flushed to disk, and flush errors are returned to the client. The docs recommend this mode for most production use ([Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)).
- `wait_for_async_insert = 0` (fire and forget): acknowledgement comes once the data is buffered, giving lower latency, but persistence is not guaranteed, and flush errors appear only in server logs and `system.asynchronous_insert_log`. The docs say to use it only if the workload can tolerate data loss ([Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)).
- The docs strongly recommend `async_insert=1, wait_for_async_insert=1` ([Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)).

#### Buffer flush conditions

The buffer flushes on whichever is reached first ([Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)):

- Data size: `async_insert_max_data_size`. The async-inserts page says "default 100 MiB", but the settings reference gives 10 MiB (10485760) as the self-managed default since 24.2 and 100 MiB (104857600) as the ClickHouse Cloud default ([settings reference](https://clickhouse.com/docs/reference/settings/session-settings/async-insert)).
- Time: `async_insert_busy_timeout_ms`, default 200 ms (1000 ms on Cloud). Adaptive timeout (`async_insert_use_adaptive_busy_timeout`) is on by default since 24.2 and moves the timeout between `async_insert_busy_timeout_min_ms` (default 50 ms) and `async_insert_busy_timeout_max_ms` (default 200 ms, 1000 ms on Cloud).
- Query count: `async_insert_max_query_number`, default 450.
- Each flush creates at least one part per distinct partition key value in the buffer.
- `SYSTEM FLUSH ASYNC INSERT QUEUE` flushes all pending buffers, useful before shutdown or maintenance.

#### Client-side batching versus async

- The docs say async inserts are meant for clients that cannot practically batch, such as large fleets of agents sending small logs, metrics or traces; where client-side batching is feasible it is the better choice ([Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)).
- Async inserts do not eliminate part explosion: a high-cardinality partition key can still cause "too many parts" ([Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)).
- Parsing and validation happen at flush time, and a bad row causes that query's whole payload to be rejected ([Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)).

**Design takeaway:** many small podcast-host webhooks that each post a handful of download events are the async-insert case; the transcript pipeline, which already produces big batches per episode, should batch on the client and keep `wait_for_async_insert=1` if it uses async at all.

### 2.4 The Kafka table engine

#### Pattern

1. Create a table with `ENGINE = Kafka()` and the required settings `kafka_broker_list`, `kafka_topic_list`, `kafka_group_name`, `kafka_format`.
2. Create a target table with the structure you want (a MergeTree-family table).
3. Create a materialized view that selects from the Kafka table and writes into the target.

([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka))

```sql
-- illustrative
CREATE TABLE downloads_queue (episode_id UInt64, ts DateTime, ip String)
ENGINE = Kafka()
SETTINGS kafka_broker_list = 'broker:9092', kafka_topic_list = 'downloads',
         kafka_group_name = 'ch_downloads', kafka_format = 'JSONEachRow';

CREATE MATERIALIZED VIEW downloads_mv TO downloads AS
SELECT episode_id, ts, ip FROM downloads_queue;
```

- Direct `SELECT` from a Kafka table is not particularly useful except for debugging ([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- One Kafka table can feed many materialized views; the views do not read the table directly but receive new records in blocks. Messages are batched by `max_insert_block_size`, and a block that does not fill within `stream_flush_interval_ms` is flushed anyway ([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- To stop consumption or change logic, detach and reattach the view; before an `ALTER` on the target the docs recommend disabling the view ([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- The Kafka engine does not support column default values; put defaults in the materialized view ([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- `kafka_num_consumers` total should not exceed the topic's partition count ([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- Error handling: `kafka_skip_broken_messages` skips up to N unparseable messages per block; `kafka_handle_error_mode` accepts `default`, `stream` (adds `_error` and `_raw_message` columns) or `dead_letter_queue` ([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).

#### Delivery semantics as the docs state them

- The integrations overview lists the Kafka table engine and ClickPipes as at-least-once, and the Kafka Connect Sink as "exactly-once can be configured" ([Kafka integration options](https://clickhouse.com/docs/integrations/kafka)).
- The engine page tracks offsets per consumer group; to re-read data use a new group name. With `kafka_keeper_path` set (the Keeper-based variant, which the page labels experimental), a failed insert re-consumes the same number of messages, which enables deduplication ([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- Durability caveat from the same page: offsets can be committed before inserted rows are fsynced, so if the page cache is lost in that window the consumer resumes past those messages and rows are lost with no error. The mitigation is `fsync_after_insert = 1` and `fsync_part_directory = 1` on every target MergeTree table, including cascaded views ([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).

#### Alternatives and how the docs position them

- ClickPipes for Kafka: a managed integration platform, "the recommended option if you're a ClickHouse Cloud user"; ingest only, no push to Kafka ([Kafka integration options](https://clickhouse.com/docs/integrations/kafka)). The engine page also recommends ClickPipes, citing private network support, independent scaling of ingestion and cluster resources, and monitoring ([Kafka table engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- Kafka Connect Sink: "recommended if you prefer high configurability or are already a Kafka Connect user"; the docs call it operationally complex to set up and maintain ([Kafka integration options](https://clickhouse.com/docs/integrations/kafka)).
- Kafka table engine: bundled with open-source ClickHouse, "recommended if you're self-hosting ClickHouse and need a low entry barrier option"; it is the only one of the three that also supports writing to Kafka ([Kafka integration options](https://clickhouse.com/docs/integrations/kafka)).

**Design takeaway:** for a self-hosted learning cluster, `downloads_queue` plus a materialized view into `downloads` is the lowest-effort path, but I must treat it as at-least-once and plan for duplicates (section 2.5).

### 2.5 Deduplication

Note: the pages I read describe behaviour for version 26.2 and later; older versions have different defaults, called out below as the docs do.

#### Insert (block-level) deduplication on retries

- Only `*MergeTree` engines support insert deduplication ([Deduplicating inserts on retries](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).
- Replicated tables keep a deduplication log by default, sized by `replicated_deduplication_window` and `replicated_deduplication_window_seconds`. Non-replicated tables use `non_replicated_deduplication_window`, which defaults to 0, so a plain `MergeTree` deduplicates nothing until it is set positive ([same page](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).
- Main query-level switch: `deduplicate_insert`, defaults to `enable`, and becomes `backward_compatible_choice` when the `compatibility` setting is below 26.2 (values `enable`, `disable`, `backward_compatible_choice`). `insert_deduplicate` and `async_insert_deduplicate` are legacy and only read under `backward_compatible_choice`; to disable, set `deduplicate_insert = disable` ([same page](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).
- `insert_deduplication_token` (default empty string) identifies an insert by a user-supplied string instead of by data hash and takes priority over the hash ([same page](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).
- `INSERT ... SELECT` is governed by `deduplicate_insert_select` (default `enable_when_possible`) and needs a stable `SELECT` (an `ORDER BY ALL` and a single-stream pipeline) or a non-empty `insert_deduplication_token` ([same page](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).
- Limits: retries must continue until they succeed; if all fail, whether the data landed is unknown. Deduplication can fail if more than the window number of other inserts happen during the retry sequence ([same page](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).

```sql
-- illustrative: a retry of the same batch carries the same token
INSERT INTO brand_mentions
SETTINGS insert_deduplication_token = 'episode-8841-batch-3'
VALUES (...);
```

#### Async inserts

- Synchronous and asynchronous inserts share one deduplication log and compute `block_id`s the same way, so switching modes keeps retries deduplicated ([Deduplicating inserts on retries](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).
- For async inserts, deduplication applies per query within a flushed batch: a duplicate query's rows are dropped and the rest of the batch is inserted ([same page](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries), [Asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)).
- Before 26.2 async deduplication was off by default and used `async_insert_deduplicate` ([Deduplicating inserts on retries](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).

#### Interaction with materialized views

- Data inserted into a source table is also pushed to dependent materialized view targets and deduplicated there. Deduplication in dependent tables requires `deduplicate_insert` plus `deduplicate_blocks_in_dependent_materialized_views` (default 1, enabled since 26.2) ([Deduplicating inserts on retries](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).
- For async inserts a view must emit one output block per input block, otherwise ClickHouse throws `NOT_IMPLEMENTED`; workarounds are setting `deduplicate_blocks_in_dependent_materialized_views = 0` or using synchronous inserts ([same page](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).
- If a materialized view throws, the INSERT fails by default; the docs suggest retrying with insert deduplication ([CREATE VIEW](https://clickhouse.com/docs/sql-reference/statements/create/view)).

#### Versus ReplacingMergeTree

- Insert deduplication recognises the same inserted block resent (by data hash or token) within a bounded window ([Deduplicating inserts on retries](https://clickhouse.com/docs/guides/developer/deduplicating-inserts-on-retries)).
- ReplacingMergeTree deduplicates rows with the same `ORDER BY` key during background merges "at an unknown time", so duplicates can remain; it is for clearing duplicates to save space and does not guarantee their absence ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- They solve different problems: the first protects against retried batches, the second against multiple versions of the same logical row.

**Design takeaway:** give each Kafka-sourced or retried batch of `brand_mentions` a deterministic `insert_deduplication_token` so a retry is a no-op; use ReplacingMergeTree only where one logical row (an episode's transcript status) is genuinely rewritten over time.

## 3. Materialized views and projections

### 3.1 Incremental materialized views

- A ClickHouse materialized view is "just a trigger that runs a query on blocks of data as they're inserted into a table" ([Incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- Results go to a target table named by `TO`; the view updates in real time, unlike refreshable views ([same page](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- Aggregation applies only to the batch of freshly inserted data, and columns are matched by name, not position ([CREATE VIEW](https://clickhouse.com/docs/sql-reference/statements/create/view)).
- The view only reflects data inserted after it was created, unless backfilled ([CREATE VIEW](https://clickhouse.com/docs/sql-reference/statements/create/view)).

```sql
-- illustrative
CREATE TABLE brand_mentions_daily
(
    day Date, brand_id UInt32, podcast_id UInt32, mentions UInt64
)
ENGINE = SummingMergeTree
ORDER BY (brand_id, podcast_id, day);

CREATE MATERIALIZED VIEW brand_mentions_daily_mv TO brand_mentions_daily AS
SELECT toDate(ts) AS day, brand_id, podcast_id, count() AS mentions
FROM brand_mentions
GROUP BY day, brand_id, podcast_id;
```

#### SummingMergeTree, AggregatingMergeTree, -State / -Merge

- SummingMergeTree replaces all rows with the same ordering key with one row containing summed numeric columns ([Incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- AggregatingMergeTree stores partial aggregate states in `AggregateFunction` columns, written with `-State` functions (for example `quantileState(0.999)(x)`) and read with `-Merge` functions (for example `avgMerge(col)`); the docs say partial aggregation states are necessary to compute correct results ([same page](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- The view's `GROUP BY` should match the target table's `ORDER BY` ([same page](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).

```sql
-- illustrative: distinct listeners per brand per day as a state
CREATE TABLE brand_reach_daily
(day Date, brand_id UInt32, listeners AggregateFunction(uniq, UInt64))
ENGINE = AggregatingMergeTree ORDER BY (brand_id, day);

SELECT brand_id, day, uniqMerge(listeners) FROM brand_reach_daily GROUP BY brand_id, day;
```

#### Why reads must still aggregate

- Merging is asynchronous, so a query can see more than one row per key; the docs say to use `FINAL` or re-aggregate with `GROUP BY` at query time ([Incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- Each inserted block produces its own partial row in the target; collapsing happens later in merges ([same page](https://clickhouse.com/docs/materialized-view/incremental-materialized-view), [CREATE VIEW](https://clickhouse.com/docs/sql-reference/statements/create/view)).

#### Backfilling

- The incremental-MV page backfills by inserting existing rows into the source (or a `Null`-engine stand-in), for example `INSERT INTO posts_null SELECT * FROM posts`, so the view processes them ([Incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- `POPULATE` is available with `TO`, and the target may already hold data. By default population is atomic only for MergeTree-family and Memory sources in Atomic databases; otherwise "rows inserted during the population can be missed or duplicated". The atomicity is local to one server, not cluster-wide ([CREATE VIEW](https://clickhouse.com/docs/sql-reference/statements/create/view)).
- `POPULATE` cannot be combined with `REFRESH`; a refreshable view is filled by its first refresh, and the docs recommend `EMPTY` in that case ([CREATE VIEW](https://clickhouse.com/docs/sql-reference/statements/create/view)).

#### What an MV does not see

- Changes to existing source data (updates, deletes, dropped partitions) "does not change the materialized view" ([CREATE VIEW](https://clickhouse.com/docs/sql-reference/statements/create/view)). The pages I read do not discuss background merges of the source as a separate case; the trigger model (blocks at insert time) is the documented explanation.
- With joins, the view triggers only on inserts to the source table, the left-most table in the query; changes to right-side tables do not update existing results. The docs suggest pre-inserting dimension data, limiting joined columns, and considering dictionaries for simple lookups ([Incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- The source table in the view query is replaced by the inserted block, so a self-join against the same table sees only the new rows ([same page](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- `UNION ALL` is not directly supported; the workaround is one view per `SELECT`, all writing to one target ([same page](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- `parallel_view_processing` defaults to 0 (views run sequentially); 1 runs them in parallel with no ordering guarantee ([same page](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).

**Design takeaway:** `brand_mentions_daily` should be fed by a `TO` view and queried with `sum(mentions) ... GROUP BY`; if a brand alias table changes, historical rollups will not change, so the join to brand names belongs at read time or in a dictionary.

### 3.2 Refreshable materialized views

- They store a query result in a target table and re-run the query over the full dataset on a schedule, rather than on each insert ([Refreshable materialized views](https://clickhouse.com/docs/materialized-view/refreshable-materialized-view)).
- The clause must include `EVERY`, `AFTER` or `DEPENDS ON`; only one refresh per view runs at a time and missed refreshes are not caught up ([CREATE VIEW](https://clickhouse.com/docs/sql-reference/statements/create/view)).
- Without `APPEND` each refresh atomically replaces the target contents; with `APPEND` it adds rows (for example periodic snapshots) ([Refreshable materialized views](https://clickhouse.com/docs/materialized-view/refreshable-materialized-view)).
- `SYSTEM REFRESH VIEW` forces a refresh; `system.view_refreshes` shows status such as `last_success_time` and `next_refresh_time` ([same page](https://clickhouse.com/docs/materialized-view/refreshable-materialized-view)).
- When the docs suggest them: incremental views are preferred for most cases and "typically scale much better"; refreshable views fit when the incremental process "isn't required or isn't applicable", for example a complex join, and for batch tasks such as denormalization ([same page](https://clickhouse.com/docs/materialized-view/refreshable-materialized-view)).
- `APPEND INCREMENTAL` processes only new rows but requires a single plain MergeTree source and rejects JOINs, UNIONs, subqueries, views and table functions ([CREATE VIEW](https://clickhouse.com/docs/sql-reference/statements/create/view)).
- Views not coordinated through ClickHouse Keeper forget when they last refreshed, so after a restart they can all refresh at once ([Refreshable materialized views](https://clickhouse.com/docs/materialized-view/refreshable-materialized-view)).

```sql
-- illustrative
CREATE MATERIALIZED VIEW campaign_attribution_mv
REFRESH EVERY 10 MINUTE TO campaign_attribution AS
SELECT c.campaign_id, m.podcast_id, count() AS exposures
FROM campaigns c JOIN brand_mentions m ON m.brand_id = c.brand_id
GROUP BY c.campaign_id, m.podcast_id;
```

**Design takeaway:** campaign attribution joins mentions to campaign dimensions and download windows, which an incremental view only evaluates against the left-most table's new rows; a refreshable view recomputes the whole join, which is the case the docs point to.

### 3.3 Projections

- A projection is "an additional, hidden table to the original table", with its own row order and primary index, and it can precompute aggregates ([Projections](https://clickhouse.com/docs/data-modeling/projections)).
- Normal projection: a reordering such as `SELECT * ORDER BY x`; the page suggests selecting a subset of columns to reduce storage. Aggregate projection: includes `GROUP BY`, and the hidden table uses `AggregatingMergeTree` ([same page](https://clickhouse.com/docs/data-modeling/projections)).
- From 25.5 a projection can store only the sorting key plus `_part_offset`, acting like an index and reading the rest from the base table, trading extra I/O for storage ([same page](https://clickhouse.com/docs/data-modeling/projections)).

```sql
-- illustrative
ALTER TABLE brand_mentions
  ADD PROJECTION by_podcast (SELECT * ORDER BY podcast_id, ts);
ALTER TABLE brand_mentions MATERIALIZE PROJECTION by_podcast
  SETTINGS mutations_sync = 1;
```

- Selection is automatic: queries target the original table and ClickHouse picks the structure that returns the correct result while reading the least data. `optimize_use_projections` is on by default; `system.query_log` has a `projections` column showing which was used ([same page](https://clickhouse.com/docs/data-modeling/projections)).
- `ADD PROJECTION` covers only newly inserted data; `MATERIALIZE PROJECTION` populates existing data ([same page](https://clickhouse.com/docs/data-modeling/projections)).
- Cost: data is effectively written twice, and the docs advise testing the effect on insert speed and storage before deploying ([same page](https://clickhouse.com/docs/data-modeling/projections)).
- Limitations listed: TTL must match the source table; no chaining; no joins or `WHERE` in the definition; lightweight updates and deletes are not supported on tables with projections; filters must reference the stored column directly (a condition like `toYear(date)` may bypass the projection) ([same page](https://clickhouse.com/docs/data-modeling/projections)). The lightweight DELETE page adds that `DELETE` is blocked on projection tables by default and that `lightweight_mutation_projection_mode` changes this ([DELETE](https://clickhouse.com/docs/sql-reference/statements/delete)).

#### Projections versus materialized views (as the docs compare them)

| Aspect | Projection | Materialized view |
|---|---|---|
| Maintenance | automatic, in sync with table | updated on insert via a target table |
| Querying | query the one original table | client picks target table or rewrites query |
| TTL | must match source | can differ |
| Chaining | not supported | supported |
| Joins and filters in definition | not supported | supported |

Source: [Projections](https://clickhouse.com/docs/data-modeling/projections). The page recommends projections when a complete reordering is needed, or when users accept the extra storage and write overhead.

**Design takeaway:** a second sort order on `brand_mentions` (by `podcast_id`) is a normal projection; the daily rollup to a different table with its own TTL is a materialized view.

## 4. Updates and deletes

### 4.1 Mutations (ALTER TABLE ... UPDATE / DELETE)

- Updates and deletes via `ALTER TABLE` are called mutations ([Updating and deleting data](https://clickhouse.com/docs/guides/developer/mutations)).
- For `*MergeTree` tables they execute by rewriting whole data parts; parts are swapped for their mutated versions as each is ready, with no atomicity, so a `SELECT` during a mutation can read a mix of mutated and unmutated parts ([ALTER](https://clickhouse.com/docs/sql-reference/statements/alter)).
- Data inserted before the mutation was submitted will be mutated; mutations do not block inserts ([ALTER](https://clickhouse.com/docs/sql-reference/statements/alter)).
- Asynchronous: the statement returns once the entry is recorded and the work runs in the background ([ALTER](https://clickhouse.com/docs/sql-reference/statements/alter)); "by default, it is asynchronous", and `mutations_sync` defines the synchronicity ([ALTER UPDATE](https://clickhouse.com/docs/sql-reference/statements/alter/update)).
- Heavy: the `ALTER TABLE` prefix signals "this is a heavy operation not designed for frequent use" ([ALTER UPDATE](https://clickhouse.com/docs/sql-reference/statements/alter/update)).
- Columns in the primary or partition key cannot be updated ([ALTER UPDATE](https://clickhouse.com/docs/sql-reference/statements/alter/update)).
- On non-replicated MergeTree tables, use `IN PARTITION` to limit the mutation ([ALTER UPDATE](https://clickhouse.com/docs/sql-reference/statements/alter/update)).
- A mutation survives server restarts, cannot be rolled back, and a stuck one can be cancelled with `KILL MUTATION` ([ALTER](https://clickhouse.com/docs/sql-reference/statements/alter)).

#### Monitoring

`system.mutations` has one row per mutation command ([system.mutations](https://clickhouse.com/docs/operations/system-tables/mutations)). Useful columns: `command`, `create_time`, `is_done`, `parts_to_do`, `parts_to_do_names`, `latest_fail_reason`, `latest_failed_part`. `parts_to_do` can be 0 while the mutation is unfinished, because a long-running INSERT may create a new part that needs mutating (same page).

```sql
-- illustrative
SELECT mutation_id, command, create_time, is_done, parts_to_do, latest_fail_reason
FROM system.mutations
WHERE table = 'brand_mentions' AND NOT is_done;
```

**Design takeaway:** correcting a misattributed brand on a few thousand `brand_mentions` rows by mutation rewrites every affected part; keep it for rare repairs, not for a per-episode workflow.

### 4.2 Lightweight deletes (DELETE FROM)

- `DELETE FROM t WHERE ...` works only with the `*MergeTree` family and is "lightweight" in contrast with the heavyweight `ALTER TABLE ... DELETE` ([DELETE](https://clickhouse.com/docs/sql-reference/statements/delete)).
- Mechanism: rows are marked as deleted through a hidden `_row_exists` column (visible rows `True`, deleted rows `False`), which exists only in parts where some rows were deleted. `SELECT` is rewritten to add `PREWHERE _row_exists`. Internally it becomes `ALTER TABLE ... UPDATE _row_exists = 0 WHERE ...` ([same page](https://clickhouse.com/docs/sql-reference/statements/delete)).
- Only the `_row_exists` column is rewritten and unaffected parts are hardlinked; `ALTER TABLE ... DELETE` recreates affected parts. Compact parts still rewrite all columns because they share one file ([same page](https://clickhouse.com/docs/sql-reference/statements/delete)).
- Caveats: rows are physically removed only in a later merge. By default the statement waits for the marking to finish (`lightweight_deletes_sync`); if disabled it returns immediately and data may stay visible until the background mutation completes. Large deletes can hurt SELECT performance, and a long mutation queue (mutations run sequentially), many parts and Compact parts can slow deletes ([same page](https://clickhouse.com/docs/sql-reference/statements/delete)).
- For predictable physical removal the docs point to the `min_age_to_force_merge_seconds` table setting or `ALTER TABLE ... DELETE`; for all rows use `TRUNCATE TABLE`; for frequent deletes consider a custom partitioning key with `DROP PARTITION` ([same page](https://clickhouse.com/docs/sql-reference/statements/delete)).
- Requires the `ALTER DELETE` privilege ([same page](https://clickhouse.com/docs/sql-reference/statements/delete)).

**Design takeaway:** a takedown request for one show's transcripts is a fit for `DELETE FROM brand_mentions WHERE podcast_id = ...`; do not use it as the way to retire last year's data.

### 4.3 Lightweight UPDATE and patch parts

- The `ALTER UPDATE` page lists "alternative lightweight update using patch parts" in its see-also ([ALTER UPDATE](https://clickhouse.com/docs/sql-reference/statements/alter/update)).
- Status: the page I read ([UPDATE](https://clickhouse.com/docs/reference/statements/update)) does not state a beta or experimental label or a version number. I therefore do not claim one; check the page for the version you run.
- Requirements: MergeTree, ReplacingMergeTree, CollapsingMergeTree or VersionedCollapsingMergeTree (including Replicated and Shared variants); table settings `enable_block_number_column` and `enable_block_offset_column` so `_block_number` and `_block_offset` are materialized; the `ALTER UPDATE` privilege ([same page](https://clickhouse.com/docs/reference/statements/update)).
- How it works: a patch part is a special data part containing only the updated columns and rows. `UPDATE` behaves like `INSERT ... SELECT` and returns once the patch part is created. `SELECT` applies patches at read time, and later merges and mutations fold them into data parts; `APPLY PATCHES` forces materialization as a mutation ([same page](https://clickhouse.com/docs/reference/statements/update)).
- The docs describe it as designed for roughly 10% of the table or less; for larger updates use `ALTER TABLE ... UPDATE` ([same page](https://clickhouse.com/docs/reference/statements/update)).
- Limitations: key and partition columns cannot be updated; skipping indexes are not used for columns in parts with pending patches; projections are not used while any patch part exists; frequent small updates can cause "too many parts", so batch them (for example with `IN`) ([same page](https://clickhouse.com/docs/reference/statements/update)).
- The page does not use the term "on-the-fly update"; query-time patch application is its equivalent. I did not find an `apply_mutations_on_fly` description in the docs pages I fetched, so I leave it out.

```sql
-- illustrative
UPDATE episodes SET transcript_status = 'final' WHERE episode_id IN (8841, 8842);
```

**Design takeaway:** flipping a status column for a small batch of episodes fits patch parts; it is still an insert-like write, so batch the ids in one statement.

### 4.4 Alternatives the docs recommend for frequent changes

The mutations guide lists deduplication-based approaches (update or delete without generating a mutation), lightweight updates and lightweight deletes as alternatives ([Updating and deleting data](https://clickhouse.com/docs/guides/developer/mutations)).

#### ReplacingMergeTree upserts

- Rows with the same `ORDER BY` key (not `PRIMARY KEY`) are deduplicated during background merges; timing is unknown, so some duplicates may remain ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- Without `ver` the most recently inserted row wins; with `ver` the highest version wins, and ties keep the last inserted row ([same page](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- `is_deleted` (UInt8, 1 = delete row) needs `ver`; by default the last row for a key is kept even if it is a delete row, and permanent removal needs `allow_experimental_replacing_merge_with_cleanup` plus min-age merge settings or `OPTIMIZE TABLE ... FINAL CLEANUP` ([same page](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- Queries can otherwise count duplicates; `FINAL` applies deduplication at query time (the docs' example shows `count()` returning 200 and `count() ... FINAL` returning 100) ([same page](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).

```sql
-- illustrative
CREATE TABLE episode_status
(episode_id UInt64, status String, updated_at DateTime)
ENGINE = ReplacingMergeTree(updated_at) ORDER BY episode_id;
SELECT * FROM episode_status FINAL WHERE episode_id = 8841;
```

#### CollapsingMergeTree

- A `Sign` Int8 column marks state rows (1) and cancel rows (-1); background merges asynchronously collapse pairs with the same sorting key apart from `Sign` ([CollapsingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/collapsingmergetree)).
- The writer must track each object's current state to emit a correct cancel row copying the earlier row's key values; results depend strongly on a consistent change history ([same page](https://clickhouse.com/docs/engines/table-engines/mergetree-family/collapsingmergetree)).
- Reads need `sum(Sign)` instead of `count()` and `sum(x * Sign)` instead of `sum(x)`; `min` and `max` cannot be computed correctly; `FINAL` is not recommended over large scans ([same page](https://clickhouse.com/docs/engines/table-engines/mergetree-family/collapsingmergetree)).
- The docs suggest it for frequently changing object state where in-place updates are costly and sequential writes are preferred ([same page](https://clickhouse.com/docs/engines/table-engines/mergetree-family/collapsingmergetree)).

#### Dropping partitions

- `ALTER TABLE ... DROP PARTITION` "tags the partition as inactive and deletes data completely, approximately in 10 minutes", and is replicated to all replicas ([ALTER PARTITION](https://clickhouse.com/docs/sql-reference/statements/alter/partition)).
- The DELETE page recommends a custom partitioning key plus `DROP PARTITION` for frequent deletes ([DELETE](https://clickhouse.com/docs/sql-reference/statements/delete)).

#### TTL

- TTL can move, delete or roll up rows or columns after an interval; removal happens only during merges, not immediately ([TTL](https://clickhouse.com/docs/guides/developer/ttl)).
- `merge_with_ttl_timeout` (default 14400 seconds) is the minimum delay before repeating a merge with delete TTL, so rules apply at least once every 4 hours by default ([same page](https://clickhouse.com/docs/guides/developer/ttl)).
- The docs recommend partitioning by the same time field used in a table-level TTL, because ClickHouse can drop whole partitions much more efficiently than deleting individual rows ([same page](https://clickhouse.com/docs/guides/developer/ttl)).
- A TTL with `GROUP BY ... SET` can roll up data before deletion; the `GROUP BY` columns must be a prefix of the primary key ([same page](https://clickhouse.com/docs/guides/developer/ttl)).

```sql
-- illustrative: raw download events kept 90 days, partitioned by month
CREATE TABLE downloads (...) ENGINE = MergeTree
PARTITION BY toYYYYMM(ts) ORDER BY (episode_id, ts)
TTL ts + INTERVAL 90 DAY;
```

**Design takeaway:** model mutable podcast state (episode metadata, transcript status) as ReplacingMergeTree rows with a version column and read with `FINAL`; keep `downloads` and `brand_mentions` append-only, expire old months by partition and TTL, and reserve mutations and lightweight deletes for rare corrections and takedowns.

## 5. Joins and dictionaries

Running example: `brand_mentions` (one row per brand mentioned in a podcast transcript), `brands`, `campaigns`, `campaign_states`, `downloads`. All SQL below is illustrative, not copied from the docs. Version numbers are as the current docs state them.

### 5.1 How a join executes

- ClickHouse reads one input completely into a matching structure (build phase); the probe phase starts only after the build phase finishes. Memory needed is "determined mostly by the size of the build side". By default the right-hand side is the build side and the left-hand side is the probe side. [Join execution](https://clickhouse.com/docs/concepts/features/operations/select/join-execution)
- `direct` is the exception: it has no build phase because the right side already exists as a key-value structure. [Join execution](https://clickhouse.com/docs/concepts/features/operations/select/join-execution)
- Filters: with `query_plan_filter_push_down` enabled the planner moves `WHERE` conditions below the join. For a `LEFT JOIN`, conditions are not pushed to the right input, and nothing is pushed into an already-filled right side such as a dictionary or into the right side of an `ASOF JOIN`. [Join execution](https://clickhouse.com/docs/concepts/features/operations/select/join-execution)

### 5.2 Join algorithms

The current docs list these (the `join_algorithm` setting accepts `grace_hash`, `hash`, `parallel_hash`, `partial_merge`, `direct`, `auto`, `full_sorting_merge`, `parallel_full_sorting_merge`, `ie_join`; `prefer_partial_merge` and `default` are deprecated). [JOIN settings](https://clickhouse.com/docs/reference/settings/session-settings/join)

- `hash`: reads the complete right side into memory and builds an in-memory hash table; the most general in-memory algorithm. Only `hash` supports multiple keys combined with `OR`. [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms)
- `parallel_hash`: the docs call it "an obsolete alias of `hash`, kept for compatibility". Whether the hash table is split is decided by `parallel_hash_join_threshold`; `hash_join_layout = serial` keeps a single table. [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms)
- `grace_hash`: a hash join that does not require the right side to fit in memory. Both sides are partitioned into buckets by key hash and processed one at a time. Needs a non-zero spill threshold and temporary storage. [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms)
- `full_sorting_merge`: sort-merge join; sorts both inputs by key, or skips the sort if input is already in key order. `parallel_full_sorting_merge` shards both inputs by key hash and runs one merge per shard; the result is unordered. [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms)
- `partial_merge`: not obsolete. Only the right side is fully sorted, in blocks with min-max indexes. Designed "for the lowest memory use when large tables are joined, at the cost of execution speed". [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms)
- `direct`: looks up each left row in the right side. Right side must be a dictionary (not range-key), an `EmbeddedRocksDB`, `KeeperMap` or `Redis` table, or, since 25.12, a `MergeTree` table, only when `join_algorithm` is set to `direct` as the single value. Requires exactly one equality on one column per side, matching the storage's single-column key. [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms)
- `ie_join`: available since 26.8, for an `ON` clause with two inequality comparisons. Block nested loop is not a `join_algorithm` value; it is the last-resort fallback for conditions nothing else can run (available since 26.10). [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms)

#### How one is chosen

- `join_algorithm` takes a list; the order sets priority and ClickHouse picks an available one per query by join kind, strictness and table engine. The default listed in the settings reference is `direct,hash,ie_join`. [JOIN settings](https://clickhouse.com/docs/reference/settings/session-settings/join)
- The algorithms are tried in order and the first that supports the join is used; if none applies the query fails. `Join`-engine right sides, `CROSS JOIN`, constant `ON` conditions and `PASTE JOIN` ignore the list. [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms)
- `auto`: (1) a spilling hash join that switches to `grace_hash` if supported and a spill threshold and temp storage are set; (2) otherwise `hash` that switches to `partial_merge` at a hard limit if supported; (3) otherwise `hash`. [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms)
- Speed guidance from the docs: reduce both inputs first and change the algorithm only after that; use `direct` for dictionary or key-value storage; `full_sorting_merge` when physical row order matches the join key; `hash` when the right table fits in memory. [Minimize and optimize JOINs](https://clickhouse.com/docs/best-practices/minimize-optimize-joins)

#### Support matrix (as the docs list it)

| Algorithm | ANY | SEMI / ANTI | ASOF |
|---|---|---|---|
| `hash` | INNER, LEFT, RIGHT | LEFT, RIGHT | INNER, LEFT |
| `grace_hash` | INNER, LEFT, RIGHT | LEFT, RIGHT | no |
| `full_sorting_merge` | INNER, LEFT, RIGHT | no | INNER, LEFT |
| `partial_merge` | INNER, LEFT | SEMI LEFT only | no |
| `direct` | LEFT | LEFT | no |

Source for the table: [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms). `ANY FULL` is rejected for every algorithm there.

#### Memory behaviour

- `max_rows_in_join` / `max_bytes_in_join` cap the right-hand structure and `join_overflow_mode` sets the action at the limit. For hash-based algorithms, reaching a limit stops the query and never makes a join spill. [Join memory management](https://clickhouse.com/docs/concepts/features/operations/select/join-memory-management)
- Spilling is driven by `max_bytes_before_external_join` or `max_bytes_ratio_before_external_join` (the smaller threshold wins if both are set); both need a configured temporary data path. `hash`/`parallel_hash` convert to `grace_hash` past the threshold. [Join memory management](https://clickhouse.com/docs/concepts/features/operations/select/join-memory-management)
- In `grace_hash` the bucket count doubles up to `grace_hash_join_max_buckets`; beyond that the query fails. A spilling join is slower than the same join in memory. `direct` and `ie_join` never spill. [Join memory management](https://clickhouse.com/docs/concepts/features/operations/select/join-memory-management)
- For memory: `grace_hash` can be tuned for very low memory by raising initial buckets (at the cost of speed); `partial_merge` minimizes memory for large tables. [Minimize and optimize JOINs](https://clickhouse.com/docs/best-practices/minimize-optimize-joins)

#### Which side is smaller, and reordering

- The docs for dictionaries advise that for regular joins "the right side of the `JOIN` is the smaller set and as small as possible". [Dictionary](https://clickhouse.com/docs/dictionary)
- Build-side swap: "Since version 24.12, the planner can swap the two inputs of a JOIN so that the smaller input becomes the build side", comparing estimated row counts and swapping for a hash-based join when the left input is estimated smaller; a `LEFT JOIN` then runs as a `RIGHT JOIN`. [Join execution](https://clickhouse.com/docs/concepts/features/operations/select/join-execution)
- Multi-table reordering: the join-execution page says the planner "can change the order in which the tables are joined"; `query_plan_optimize_join_order_limit` sets the maximum number of tables reordered, default `10`, and `1` disables reordering. That page gives no version for reordering. [Join execution](https://clickhouse.com/docs/concepts/features/operations/select/join-execution)
- The best-practices page states: "Multi-table JOIN reordering and optimizer use of available statistics are enabled by default since 25.12." Column statistics "became generally available and enabled by default in 26.3"; since 26.8 eligible tables materialize statistics on insert by default. [Minimize and optimize JOINs](https://clickhouse.com/docs/best-practices/minimize-optimize-joins)
- Without column statistics the planner derives estimates from the primary index, "and these estimates can be imprecise". [Join execution](https://clickhouse.com/docs/concepts/features/operations/select/join-execution)

Design takeaway: put `brands` (small) on the right of a join against `brand_mentions`, and still write the query so the big table is on the left; do not depend on the planner's swap or reorder on a version you have not checked.

### 5.3 Strictness and join types for analytics

- Types: INNER, LEFT/RIGHT/FULL OUTER, CROSS, NATURAL, plus SEMI/ANTI, ANY, ASOF, PASTE. Outer joins fill non-matches with defaults, or `NULL` when `join_use_nulls` is set (default `0`). [JOIN clause](https://clickhouse.com/docs/sql-reference/statements/select/join), [JOIN settings](https://clickhouse.com/docs/reference/settings/session-settings/join)
- `join_default_strictness` defaults to `ALL` (every match, Cartesian product of matches); `ANY` joins only the first match found. [JOIN settings](https://clickhouse.com/docs/reference/settings/session-settings/join)
- `ANY` returns at most one match per left row and no Cartesian product; which row is returned "is not defined". [Joining tables](https://clickhouse.com/docs/guides/joining-tables)
- `ANTI` acts as a denylist on join keys with no Cartesian product; `ANY` and `SEMI` normally keep one row per group sharing a key. [JOIN clause](https://clickhouse.com/docs/sql-reference/statements/select/join)
- `ASOF` is a strictness combined with `INNER` or `LEFT`, not an algorithm. Syntax is any number of equality conditions plus exactly one closest-match condition (`>`, `>=`, `<`, `<=`); with `USING`, the ASOF column is last. Only `hash` and `full_sorting_merge` support it, and it is not supported in the `Join` table engine. [JOIN clause](https://clickhouse.com/docs/sql-reference/statements/select/join)

```sql
-- illustrative: campaign state in force at the moment of each mention
SELECT m.mention_id, m.mentioned_at, s.status
FROM brand_mentions AS m
ASOF LEFT JOIN campaign_states AS s
  ON m.brand_id = s.brand_id AND m.mentioned_at >= s.effective_from;
```

Design takeaway: "latest campaign state at mention time" is an `ASOF LEFT JOIN`; the state history table is the right (build) side, so keep it compact. Use `ANY` when a lookup should return a single row so a duplicated dimension row cannot multiply mentions.

### 5.4 Minimizing joins

Recommendations from the docs, in the order they give them: [Minimize and optimize JOINs](https://clickhouse.com/docs/best-practices/minimize-optimize-joins)

- Denormalization "shifts computational work from query time to insert or preprocessing time"; for latency-sensitive analytical queries it is "strongly recommended", applied to frequently queried attributes only.
- Use materialized views "to incrementally compute aggregates instead of duplicating entire sub-tables".
- If a join is required: use `ANY` joins when one match is enough, reduce both sides before the join, and join on table sorting keys when possible.
- "Consider `IN` instead of `INNER JOIN`"; to check that a match exists use `IN` or `LEFT SEMI JOIN`. The page's rewrite example is valid only when "the left-hand JOIN key is unique".
- Use dictionaries for repeated key-value lookups; prefer the `Join` table engine for reusable lookups; avoid disk-spilling joins.

The Postgres migration guide agrees on direction: normalized schemas spread over many tables, and "denormalization can be beneficial at times to optimize JOIN performance". [Data modeling techniques](https://clickhouse.com/docs/migrations/postgresql/data-modeling-techniques)

For distributed `IN`, see 6.4.

```sql
-- illustrative: pre-join at insert time with a materialized view
CREATE MATERIALIZED VIEW mentions_enriched_mv TO mentions_enriched AS
SELECT m.*, dictGet('brands_dict', 'brand_name', m.brand_id) AS brand_name
FROM brand_mentions AS m;
```

Design takeaway: carry `brand_name` and `category` on each mention row (or enrich at insert) and keep joins for the few queries that need history, such as the ASOF above.

### 5.5 Dictionaries

- A dictionary is "a mapping (`key -> attributes`) that is convenient for various types of reference lists"; the docs say it is easier and more efficient to use dictionaries with functions than a `JOIN` with reference tables. `CREATE DICTIONARY` (DDL) is the recommended method; configuration-file dictionaries are not supported in ClickHouse Cloud. [Dictionaries](https://clickhouse.com/docs/sql-reference/dictionaries)
- `SOURCE` defines where data comes from, for example a ClickHouse table, HTTP or PostgreSQL; for a ClickHouse table source the page says to use a dedicated user with `SELECT` on the source. [Dictionaries](https://clickhouse.com/docs/sql-reference/dictionaries)
- Dictionaries are "usually held in memory" (`ssd_cache` is the exception) and stored uncompressed, so they can be significantly larger than the compressed table; memory must be reserved per node. [Dictionary](https://clickhouse.com/docs/dictionary), [Dictionary best practices](https://clickhouse.com/docs/concepts/features/dictionaries/best-practices)

#### Layouts

Non-`complex_key` layouts use a `UInt64` key; `complex_key_*` layouts take a composite key. [Layouts](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts)

- `flat`: arrays indexed by key; fastest; keys must be `UInt64` and bounded by `max_array_size`. The best-practices page puts the default cap at 500,000 and says hitting it is a signal to switch to `hashed_array`. [Layouts](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts), [Dictionary best practices](https://clickhouse.com/docs/concepts/features/dictionaries/best-practices)
- `hashed`, `sparse_hashed`, `complex_key_hashed`: hash table, no key size limit; `sparse_hashed` trades CPU for memory. `hashed_array`: attributes in arrays plus a hash from key to index, memory-efficient with many attributes, and "the recommended default for most use cases". [Layouts](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts), [Dictionary best practices](https://clickhouse.com/docs/concepts/features/dictionaries/best-practices)
- `range_hashed`: hash table of ordered ranges; lookup takes a key plus a date or numeric range, with `range_lookup_strategy` (`min` default, `max`) for overlaps. [range_hashed](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts/range-hashed)
- `cache` / `ssd_cache`: fixed-size cache of frequently accessed keys. The best-practices page says they are "Not recommended for latency-sensitive workloads or reliable insert-time enrichment" (each server warms its own cache). [Layouts](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts), [Dictionary best practices](https://clickhouse.com/docs/concepts/features/dictionaries/best-practices)
- `direct`: no in-memory storage; queries the source on every request. Suggested "when the data changes too frequently to cache or when the dictionary is too large for memory". [Layouts](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts), [Dictionary best practices](https://clickhouse.com/docs/concepts/features/dictionaries/best-practices)
- `ip_trie`: IP lookups by network prefix; key is a single `String` attribute holding a prefix; the most specific match is returned; "Data must completely fit into RAM". [ip_trie](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts/ip-trie)
- Also listed: `hierarchical`, `polygon`, `regexp_tree`. For best query performance the docs name `flat`, `hashed` and `complex_key_hashed`. [Layouts](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts)

#### LIFETIME refresh

- `LIFETIME(MIN 300 MAX 360)`: ClickHouse picks a uniformly random time in the range, spreading source load across servers. `LIFETIME(0)` prevents timer-based updates (reload still possible via `SYSTEM RELOAD DICTIONARY`). [LIFETIME](https://clickhouse.com/docs/reference/statements/create/dictionary/lifetime)
- `invalidate_query` (source setting) reloads only when its result changes; `update_field` (source setting) passes the last update time so only changed rows are requested, with `update_lag` subtracting seconds. [LIFETIME](https://clickhouse.com/docs/reference/statements/create/dictionary/lifetime)
- Updates do not block queries except the first load; a successful update swaps in atomically, and a failed one is logged while queries keep using the old version. [LIFETIME](https://clickhouse.com/docs/reference/statements/create/dictionary/lifetime)

#### dictGet versus JOIN

- `dictGet('dict', attr, id)` returns the attribute, or the configured `null_value` if the key is missing; `dictGetOrDefault` and `dictGetOrNull` handle misses explicitly. A composite key is passed as a tuple. A `range_hashed` dictionary takes the date as the last argument. [Functions for dictionaries](https://clickhouse.com/docs/sql-reference/functions/ext-dict-functions)
- A standard join builds a hash table from the right side even if `WHERE` later discards most rows; `dictGet` runs only on rows that survive filtering. The page adds that recent versions push filters before joins in many cases, so the gap is not always there. [Dictionary best practices](https://clickhouse.com/docs/concepts/features/dictionaries/best-practices)
- Dictionary functions can be called after `GROUP BY`, and attributes marked injective can be removed from `GROUP BY`. [Layouts](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts)
- `dictGet` is also usable at insert time via `MATERIALIZED` columns. [Dictionary](https://clickhouse.com/docs/dictionary)

```sql
-- illustrative: a hashed dictionary of brands
CREATE DICTIONARY brands_dict (
    brand_id UInt64,
    brand_name String,
    category String
)
PRIMARY KEY brand_id
SOURCE(CLICKHOUSE(TABLE 'brands'))
LAYOUT(HASHED())
LIFETIME(MIN 300 MAX 360);

SELECT dictGet('brands_dict', 'brand_name', brand_id) AS brand, count()
FROM brand_mentions GROUP BY brand;
```

#### Dictionary table engine and direct join

- The `Dictionary` engine "displays the dictionary data as a ClickHouse table": `CREATE TABLE t (...) ENGINE = Dictionary(dict_name)`. It exists because `dictGet*` and `system.dictionaries` are not helpful for raw data or `JOIN`. [Dictionary table engine](https://clickhouse.com/docs/engines/table-engines/special/dictionary)
- The direct join with a dictionary-backed right side is described as ClickHouse's fastest join algorithm; the dictionary page says direct joins apply only to `LEFT ANY` and the key must match the key attribute. [Dictionary](https://clickhouse.com/docs/dictionary) (Note the algorithms page lists a wider direct matrix: [JOIN algorithms](https://clickhouse.com/docs/concepts/features/operations/select/join-algorithms).)

#### When a dictionary is the wrong tool

- "Dictionaries work best when one side of a JOIN is a lookup table that fits in memory", used for small dimension tables where the key is already available. [Dictionary best practices](https://clickhouse.com/docs/concepts/features/dictionaries/best-practices)
- `dictGet` "evaluates row by row with no index support", so for filtering on many rows an indexed column is usually better. [Dictionary best practices](https://clickhouse.com/docs/concepts/features/dictionaries/best-practices)
- Not a fit for big, fast-changing sets: they are memory-resident per node, and cache layouts are discouraged for insert-time enrichment. If the full dictionary will not fit, enrich before insertion or at query time rather than relying on a warmed cache. [Dictionary best practices](https://clickhouse.com/docs/concepts/features/dictionaries/best-practices)
- The docs' `range_hashed` example is advertiser discounts with start and end dates, which maps onto campaign flight dates. [range_hashed](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts/range-hashed)

Design takeaway: `brands` and `campaigns` (small, slowly changing) fit a `hashed` or `hashed_array` dictionary refreshed by `LIFETIME`; the `downloads` fact table does not. Campaign flight dates fit `range_hashed`. Per-episode transcript data does not belong in a dictionary.

## 6. Replication, sharding and Distributed tables

### 6.1 ReplicatedMergeTree

- Compressed data from `INSERT` and `ALTER` is replicated. `CREATE`, `DROP`, `ATTACH`, `DETACH` and `RENAME` run on a single server and are not replicated. "Replication is asynchronous and multi-master": writes can go to any available server, then copy to the others with latency. Replication is per table, independent of sharding. [Replicated* engines](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication)
- Keeper role: ClickHouse Keeper stores replica metadata (ZooKeeper 3.4.5 or newer also works; Keeper is recommended). Without it you cannot create replicated tables and existing ones become read-only. "ZooKeeper is not used in `SELECT` queries." [Replicated* engines](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication)
- Parameters: `zoo_path` (table path in Keeper, unique per replicated table) and `replica_name` (unique within each shard); macros like `{shard}` and `{replica}` come from `<macros>` config, `{database}` and `{table}` are built in. [Replicated* engines](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication), [Cluster deployment](https://clickhouse.com/docs/architecture/cluster-deployment)
- The cluster-deployment guide recommends at least three Keeper nodes. [Cluster deployment](https://clickhouse.com/docs/architecture/cluster-deployment)
- Insert deduplication: identical blocks (same size, rows, order) are written once, so retrying an insert is safe. [Replicated* engines](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication)

```sql
-- illustrative: replicated local table, run once per cluster with ON CLUSTER
CREATE TABLE brand_mentions_local ON CLUSTER podcast_cluster (
    mention_id UUID, episode_id UInt64, brand_id UInt64, mentioned_at DateTime
)
ENGINE = ReplicatedMergeTree('/clickhouse/tables/{shard}/brand_mentions_local', '{replica}')
ORDER BY (brand_id, mentioned_at);
```

#### Insert quorum and read consistency

- By default "an INSERT query waits for confirmation of writing the data from only one replica"; `insert_quorum` asks for several. [Replicated* engines](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication)
- `insert_quorum` default is `0`; values below 2 disable it, 2 or more enable it, `'auto'` is `number_of_replicas / 2 + 1`. The insert succeeds only if written to the required replicas within `insert_quorum_timeout` (default 600000 ms); otherwise it fails and the block is deleted from replicas that had it. [insert_quorum settings](https://clickhouse.com/docs/reference/settings/session-settings/insert-quorum)
- `insert_quorum_parallel` defaults to `1`. With it disabled, all quorum replicas hold data from all previous inserts and further writes to the table are rejected while one is in flight. [insert_quorum settings](https://clickhouse.com/docs/reference/settings/session-settings/insert-quorum)
- `select_sequential_consistency` defaults to `0` and requires `insert_quorum_parallel` to be disabled. [Other session settings](https://clickhouse.com/docs/reference/settings/session-settings/other)
- Reads are consistent when you read from the node you wrote to (same session or native protocol). Otherwise the docs give extra steps: `SYSTEM SYNC REPLICA ... LIGHTWEIGHT`, or `select_sequential_consistency = 1`; both add load on Keeper and may be slower. They recommend a sticky connection. [Read consistency](https://clickhouse.com/docs/knowledgebase/read_consistency)
- The docs do not state a default cross-replica read guarantee beyond the above, and note that newly inserted data "might not be immediately visible across all replicas". [Read consistency](https://clickhouse.com/docs/knowledgebase/read_consistency), [Appendix](https://clickhouse.com/docs/migrations/postgresql/appendix)

Design takeaway: for `brand_mentions` default replication (acknowledged by one replica) suits near-real-time dashboards; raise `insert_quorum` only for data you cannot afford to lose, and pin dashboards to one session or node if read-your-writes matters.

### 6.2 Sharding and the Distributed engine

- A shard holds a subset of a table's data and works as a regular table that can be queried independently; a replica is a copy of a shard on another server. Sharding is used when data is too large for one server or one server is too slow. [Table shards and replicas](https://clickhouse.com/docs/guides/oss/deployment-and-scaling/shards)
- "Tables with Distributed engine do not store any data of their own." `SELECT` is sent to all shards and partial results are merged; `INSERT` is routed across shards. [Distributed engine](https://clickhouse.com/docs/engines/table-engines/special/distributed), [Table shards and replicas](https://clickhouse.com/docs/guides/oss/deployment-and-scaling/shards)
- Routing: writing needs `sharding_key` (unless one shard); the expression's result is divided by the total shard weight and the remainder picks the shard. Rows are distributed in proportion to shard weight. [Distributed engine](https://clickhouse.com/docs/engines/table-engines/special/distributed)
- Clusters are defined in the server configuration file and cannot be specified dynamically. [Distributed engine](https://clickhouse.com/docs/engines/table-engines/special/distributed)

```sql
-- illustrative
CREATE TABLE brand_mentions ON CLUSTER podcast_cluster AS brand_mentions_local
ENGINE = Distributed('podcast_cluster', currentDatabase(), 'brand_mentions_local', cityHash64(episode_id));
```

#### Choosing a sharding key

- The expression can be any expression of constants and columns that returns an integer; if a column is not evenly distributed, wrap it in a hash function such as `intHash64(UserID)`. Plain remainder is "a limited solution" and the docs say it works for dozens of servers but not hundreds or more. [Distributed engine](https://clickhouse.com/docs/reference/engines/table-engines/special/distributed)
- Sharding by the join key lets you use local `IN` or `JOIN` instead of `GLOBAL`; locating one client's data on one shard suits many small per-client queries. `optimize_skip_unused_shards` needs the key to decide which shards to query. [Distributed engine](https://clickhouse.com/docs/reference/engines/table-engines/special/distributed)
- The horizontal-scaling guide's example uses `rand()` to spread inserts randomly. [Horizontal scaling](https://clickhouse.com/docs/architecture/horizontal-scaling)

#### Inserting: Distributed versus local tables

- Through the Distributed table: it distributes the data itself. The block is first written to the local file system and then sent to remote servers in the background. [Distributed engine](https://clickhouse.com/docs/engines/table-engines/special/distributed), [Distributed engine (reference)](https://clickhouse.com/docs/reference/engines/table-engines/special/distributed)
- Directly into shard tables: the docs call this "the most optimal solution since data can be written to different shards completely independently", but then you own the sharding logic. [Distributed engine (reference)](https://clickhouse.com/docs/reference/engines/table-engines/special/distributed)

#### internal_replication and ON CLUSTER

- With `internal_replication = true` the Distributed table writes to the first healthy replica and replication of the underlying replicated table does the rest. With `false` (the default) data is written to all replicas, which the docs say is "worse than using replicated tables". [Distributed engine](https://clickhouse.com/docs/engines/table-engines/special/distributed)
- `ON CLUSTER` runs DDL on every host of a cluster; pending queries sit in a queue, and a host unavailable long enough "may not execute the query when it becomes available again". Order on a single host is guaranteed only with `distributed_ddl.pool_size = 1`. It does not apply to DML such as `INSERT`. [Distributed DDL](https://clickhouse.com/docs/sql-reference/distributed-ddl), [Cluster deployment](https://clickhouse.com/docs/architecture/cluster-deployment)

Design takeaway: shard `brand_mentions` by a hash of an id you filter or group on (for example `episode_id`), keep `brands` replicated in full to every shard (so joins stay local), and prefer batching inserts through one writer path.

### 6.3 Distributed aggregation

- For a `GROUP BY` query, data is aggregated on remote servers and "the intermediate states of aggregate functions will be sent" to the requesting server. [Distributed engine (reference)](https://clickhouse.com/docs/reference/engines/table-engines/special/distributed)
- The docs I read do not describe `distributed_group_by_no_merge` or similar settings, so I leave them out.

### 6.4 GLOBAL IN and GLOBAL JOIN

- Regular `IN`/`JOIN` against a distributed table: each remote server runs the subquery itself against its local data, so results are accurate only if each key's data sits on one server ("local IN"). A subquery on a distributed table multiplies requests: a 100-server cluster needs 10,000 elementary requests, which the docs call generally unacceptable. [IN operator](https://clickhouse.com/docs/sql-reference/operators/in)
- `GLOBAL IN`: the requester runs the subquery once, collects results in a temporary table, and sends it to each remote server. For `GLOBAL JOIN` the right table is calculated for `LEFT`/`INNER` and the left for `RIGHT`. [IN operator](https://clickhouse.com/docs/sql-reference/operators/in)
- Guidance: always use `GLOBAL IN` instead of `IN` for subqueries on distributed tables; avoid large sets; add `DISTINCT` (temporary tables are not deduplicated); cap with `max_rows_in_set` and `max_bytes_in_set`; distribute data so `GLOBAL IN` is rarely needed. [IN operator](https://clickhouse.com/docs/sql-reference/operators/in)

Design takeaway: a campaign filter such as "mentions of brands in campaign X" is a `GLOBAL IN` over a small brand-id set, or avoid it by replicating `brands` to every shard.

### 6.5 Adding shards: no automatic rebalancing

- "ClickHouse doesn't support automatic shard rebalancing." Options in the docs' order of preference: adjust shard weights (biases writes only, "doesn't assist with rebalancing existing data"); weight writes manually to the new shard; detach, move and reattach partitions (a manual operation); `INSERT FROM SELECT` into the new cluster, "a last resort". [Rebalancing data](https://clickhouse.com/docs/guides/sre/scaling-clusters)
- The Distributed engine page says you do not have to transfer old data when adding a shard, and that weighting new data toward it leaves distribution "slightly uneven". [Distributed engine](https://clickhouse.com/docs/engines/table-engines/special/distributed)

Design takeaway: pick the shard count and key with headroom; growth by adding shards means skew or manual partition moves, so partition `brand_mentions` by month to make partition moves possible.

### 6.6 ClickHouse Cloud

- SharedMergeTree is "a cloud-native replacement of the ReplicatedMergeTree engines that is optimized to work on top of shared storage", giving "a deeper separation of compute and storage". With ReplicatedMergeTree, "the metadata still resides on each of the clickhouse-servers". [SharedMergeTree](https://clickhouse.com/docs/products/cloud/features/infrastructure/shared-merge-tree)
- Replicas communicate through shared storage and `clickhouse-keeper`, with asynchronous leaderless replication; tables can have "hundreds of replicas" and scale "without shards". [SharedMergeTree](https://clickhouse.com/docs/products/cloud/features/infrastructure/shared-merge-tree)
- All inserts are quorum inserts by design, so `insert_quorum` and `insert_quorum_parallel` are not needed; `select_sequential_consistency` "doesn't require quorum inserts" but adds load on Keeper for `SELECT` queries. [SharedMergeTree](https://clickhouse.com/docs/products/cloud/features/infrastructure/shared-merge-tree), [Read consistency](https://clickhouse.com/docs/knowledgebase/read_consistency)
- The page does not cover `Distributed` tables; I make no claim about them in Cloud.

Design takeaway: on Cloud, most of 6.2 to 6.5 (shard counts, rebalancing) is replaced by scaling replicas; on self-managed it is your design problem.

## 7. When not to use ClickHouse

### 7.1 What the docs say it is for

- ClickHouse is an OLAP system, often used as a backend for analytics SaaS products. It "still doesn't have full-fledged transaction support", though it has consistent reads and writes and mutations. OLAP stores are typically columnar; OLTP typically row-based because columns make row-level appends and in-place changes costlier. [OLAP FAQ](https://clickhouse.com/docs/faq/general/olap)
- Listed drawbacks: "No full-fledged transactions"; no ability to modify or delete inserted data at a high rate and low latency (batch updates and deletes exist); and "The sparse index makes ClickHouse not so efficient for point queries retrieving single rows by their keys." [Distinctive features](https://clickhouse.com/docs/about-us/distinctive-features)
- Postgres is the classic OLTP system whose focus is ACID guarantees; ClickHouse is built for analytics, with strength in aggregation such as `GROUP BY`. OLTP databases "typically hit performance limitations when used for analytical queries over large datasets". [PostgreSQL migration overview](https://clickhouse.com/docs/migrations/postgresql/overview)

### 7.2 Against PostgreSQL and other OLTP databases

- Point lookups: see the sparse-index drawback above. The ReplacingMergeTree guide notes that for analytical workloads the Postgres primary key "is generally of little use as you will rarely perform point row lookups". [Distinctive features](https://clickhouse.com/docs/about-us/distinctive-features), [ReplacingMergeTree](https://clickhouse.com/docs/guides/replacing-merge-tree)
- Row-at-a-time updates: updates and deletes run as mutations via `ALTER TABLE`; columns in the primary or sorting key cannot be updated; for frequent updates the docs suggest deduplication (which updates without a mutation) or lightweight updates and deletes. [Mutations](https://clickhouse.com/docs/guides/developer/mutations)
- Transactions: single-block inserts are ACID in limited cases, and the Postgres appendix says ClickHouse provides ACID "under limited configurations", most simply a non-replicated `MergeTree` with one partition: "You shouldn't expect these properties outside of these cases". Multi-statement transactions are experimental, need Keeper, the Atomic database and non-replicated MergeTree, and are not supported in ClickHouse Cloud. [Appendix](https://clickhouse.com/docs/migrations/postgresql/appendix), [Transactions](https://clickhouse.com/docs/guides/developer/transactional)
- Uniqueness: the docs I read do not state that a primary key is unenforced by name. What they say: `ReplacingMergeTree` treats rows with equal `ORDER BY` values as duplicates, deduplicates in background merges ("eventual correctness only"), so a plain `SELECT` can return duplicates and `FINAL` is needed. They also say Postgres primary keys are "unique per row" while a ClickHouse key is a sparse index. [ReplacingMergeTree](https://clickhouse.com/docs/guides/replacing-merge-tree), [Data modeling techniques](https://clickhouse.com/docs/migrations/postgresql/data-modeling-techniques)
- Frequent small writes: each insert creates a storage part; docs recommend batches of at least 1,000 rows, ideally 10,000 to 100,000, roughly one insert per second; many small synchronous inserts lead to many parts and "too many parts" errors. Use async inserts when client batching is not possible (recommended: `async_insert=1,wait_for_async_insert=1`); async data is not queryable until flushed. [Selecting an insert strategy](https://clickhouse.com/docs/best-practices/selecting-an-insert-strategy), [Inserting data](https://clickhouse.com/docs/guides/inserting-data)
- Heavy many-table joins: the docs recommend denormalizing and minimizing joins (5.4); Postgres schemas are normalized across many tables. [Minimize and optimize JOINs](https://clickhouse.com/docs/best-practices/minimize-optimize-joins), [Data modeling techniques](https://clickhouse.com/docs/migrations/postgresql/data-modeling-techniques)
- Left out for lack of docs support in what I read: foreign-key constraints, and a docs claim about high-concurrency key-value access beyond the point-query drawback above.

### 7.3 Using both: Postgres plus ClickHouse

- The migration overview recommends keeping Postgres for transactions and replicating committed changes to ClickHouse with CDC, and calls real-time CDC through ClickPipes "the recommended approach" for most applications needing fresh data. For on-prem it names PeerDB. Manual bulk load plus periodic updates suits cases where real-time replication is not required, with no real-time updates. [PostgreSQL migration overview](https://clickhouse.com/docs/migrations/postgresql/overview)
- ClickPipes Postgres CDC: an initial snapshot then continuous replication through a publication and replication slot; destination tables default to `ReplacingMergeTree` (on ClickHouse Cloud the destination engine shown is SharedReplacingMergeTree) with `_peerdb_is_deleted` and `_peerdb_version` columns, so query with `FINAL` and filter deleted rows; default sync interval 60 seconds; poolers such as PgBouncer are not supported. That page does not state GA or beta status. [ClickPipes Postgres](https://clickhouse.com/docs/integrations/clickpipes/postgres)
- `MaterializedPostgreSQL` database engine: labelled experimental, enabled via `enable_database_materialized_postgresql`, "Not supported in ClickHouse Cloud", with ClickPipes recommended for Cloud. It snapshots tables then reads the WAL; new tables are not added automatically, and DDL is not replicated. [MaterializedPostgreSQL](https://clickhouse.com/docs/engines/database-engines/materialized-postgresql)

### 7.4 Decision checklist (my synthesis, not from the docs)

Each item rests on a property cited above.

- Accounts, billing, campaign configuration edits: Postgres. Row-level edits, uniqueness and transactions are limited in ClickHouse (7.2, 7.1). Replicate the config to ClickHouse via CDC for joins (7.3), landing as `ReplacingMergeTree` (query with `FINAL`).
- Mention events, transcript-derived rows: ClickHouse, inserted in batches or via async inserts (7.2) into a `MergeTree` ordered by `(brand_id, mentioned_at)`.
- Downloads (append-only, high volume): ClickHouse. Many small events should be batched or use async inserts; do not write one row per HTTP request synchronously (7.2).
- Brand and campaign lookups on the read path: a dictionary or denormalized columns, not a normalized join (5.4, 5.5); campaign-state-at-mention uses `ASOF` or `range_hashed` (5.3, 5.5).
- Rollups (mentions per brand per day): materialized views into aggregate tables (5.4).
- "Show me this one account's invoice": Postgres, since single-row retrieval is a stated ClickHouse weakness (7.1).
- Need strict read-your-writes across replicas: ClickHouse needs quorum plus sequential consistency or a sticky connection (6.1); if that is a hard requirement, keep that data in Postgres.
- Scale: one node with replication first; add shards only for volume, accepting no automatic rebalancing (6.5).

## 8. Worked design scenarios

These are scenarios I worked through to test my understanding of the earlier sections, all in one domain: a podcast ad-measurement product (brand mentions in transcripts, downloads, campaign attribution).
Each approach is a starting point to argue with; every mechanism it leans on links to the ClickHouse docs page that describes it.

### Scenario 1. Billions of ad-mention events, mentions per brand per day

Problem: store a very large, append-only stream of mention events and answer "mentions per brand per day" cheaply.

Approach:
- One MergeTree table, append-only, partitioned by month, ordered by `(brand_id, mention_date, podcast_id, episode_id)`.
- Rows are stored on disk in sorting-key order and the primary index is built from that order ([sparse primary indexes](https://clickhouse.com/docs/guides/best-practices/sparse-primary-indexes)).
- Partitioning is a data-management tool (drops, TTL, tiering), and a low-cardinality key with fewer than 100-1,000 distinct values is usually optimal, so month fits and per-day or per-brand does not ([choosing a partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)).
- Every insert creates a part that background merges later combine ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)), so writers must batch (Scenarios 7 and 8).
- The per-day count itself should come from a rollup (Scenario 3), not a scan of raw rows.

Tradeoff: the docs advise ordering key columns by ascending cardinality for compression and for filters on later columns ([sparse primary indexes](https://clickhouse.com/docs/guides/best-practices/sparse-primary-indexes)); putting `brand_id` first serves per-brand queries but gives up some of that.

```sql
-- illustrative
CREATE TABLE mentions (
  mention_ts DateTime, mention_date Date, brand_id UInt32,
  podcast_id UInt32, episode_id UInt64, confidence Float32
) ENGINE = MergeTree
PARTITION BY toYYYYMM(mention_date)
ORDER BY (brand_id, mention_date, podcast_id, episode_id);
```

### Scenario 2. Choosing ORDER BY and partition key; most queries are per podcast

Problem: decide the keys for `mentions`, and see what moves if the dominant filter becomes `podcast_id`.

Approach:
- Keep the partition key as a coarse time bucket whichever way queries lean, because partitioning is not meant to speed up queries ([choosing a partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)).
- Only the ORDER BY changes: filtering on the first key column lets ClickHouse binary-search the index marks, while filtering only on a later column falls back to a generic exclusion search that works best when the preceding column has lower cardinality ([sparse primary indexes](https://clickhouse.com/docs/guides/best-practices/sparse-primary-indexes)).
- For a per-podcast workload I would order by `(podcast_id, mention_date, brand_id)`.
- If both access patterns matter, the same page lists a second table, a materialized view or a projection.
- A projection is the most transparent since ClickHouse picks the best table version automatically, and it can have a different row order and primary index ([projections](https://clickhouse.com/docs/data-modeling/projections)).

Tradeoff: a second ordering costs extra storage and insert work ([projections](https://clickhouse.com/docs/data-modeling/projections)), and the base ordering is still only good for one of the two patterns.

```sql
-- illustrative: add a podcast-first ordering as a projection
ALTER TABLE mentions ADD PROJECTION by_podcast
  (SELECT * ORDER BY podcast_id, mention_date, brand_id);
```

### Scenario 3. Sub-second top brands per week and share of voice

Problem: dashboards need weekly top brands and share of voice quickly, without scanning raw mentions.

Approach:
- An incremental materialized view writing into a rollup table; the view is a trigger that runs its query on each inserted block and writes to a separate target table ([incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- For plain counts use SummingMergeTree, which replaces rows with the same ordering key by one summed row at merge time; because merges are asynchronous, queries still `sum()` with `GROUP BY` ([SummingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/summingmergetree)).
- For anything non-additive use AggregatingMergeTree with `-State` on write and `-Merge` on read ([AggregatingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/aggregatingmergetree)).
- Projections are the alternative; the docs say they are kept in sync automatically but recommend them mainly for full reorderings, and call materialized views generally more effective for maintaining aggregates ([projections](https://clickhouse.com/docs/data-modeling/projections)).
- Share of voice is then `brand_count / sum(brand_count)` computed over the small rollup at query time.

Tradeoff: the rollup only answers the questions its key anticipated, and the incremental view shifts cost to insert time ([materialized view best practices](https://clickhouse.com/docs/best-practices/use-materialized-views)).

```sql
-- illustrative
CREATE TABLE mentions_by_brand_day (mention_date Date, brand_id UInt32, n UInt64)
ENGINE = SummingMergeTree ORDER BY (mention_date, brand_id);
CREATE MATERIALIZED VIEW mentions_by_brand_day_mv TO mentions_by_brand_day AS
SELECT mention_date, brand_id, count() AS n FROM mentions GROUP BY mention_date, brand_id;
```

### Scenario 4. Distinct episodes and distinct listeners in a rollup

Problem: a daily rollup of distinct listeners cannot be summed into a weekly figure.

Approach:
- Store aggregate function states, not final numbers: AggregatingMergeTree uses `AggregateFunction` columns written with `-State` (for example `uniqState`) and read with `-Merge` plus `GROUP BY` ([AggregatingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/aggregatingmergetree)).
- Partial states are needed because combining sub-range results (the page's example is averages) gives wrong answers ([incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)); adding daily distinct counts double-counts a listener seen on two days for the same reason.
- `uniq` is the default recommendation in almost all cases and uses adaptive sampling ([uniq](https://clickhouse.com/docs/sql-reference/aggregate-functions/reference/uniq)).
- `uniqCombined` is documented as more accurate and lower in memory, usually slightly slower ([uniqCombined](https://clickhouse.com/docs/sql-reference/aggregate-functions/reference/uniqcombined)).
- `uniqExact` is exact but its state grows without bound as distinct values increase ([uniqExact](https://clickhouse.com/docs/sql-reference/aggregate-functions/reference/uniqexact)).

Tradeoff: approximate states mean the number can differ slightly from a true count; exact states cost unbounded memory.

```sql
-- illustrative
CREATE TABLE listeners_by_day (d Date, podcast_id UInt32, u AggregateFunction(uniq, UInt64))
ENGINE = AggregatingMergeTree ORDER BY (d, podcast_id);
SELECT podcast_id, uniqMerge(u) FROM listeners_by_day
WHERE d >= today() - 7 GROUP BY podcast_id;
```

### Scenario 5. At-least-once download events and deduplicated counts

Problem: the queue redelivers, so the same download can arrive twice.

Approach: layer three defences, cheapest first.
- Insert-level: replicated tables deduplicate repeated identical blocks, so a retried batch is safe ([data replication](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication)).
- Async inserts dedupe per user query, and a plain MergeTree needs `non_replicated_deduplication_window` set to a positive value ([asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)). That only catches identical batches.
- Rows built with something like `DEFAULT now()` produce unique checksums, and `insert_deduplication_token` is the documented workaround ([deduplication](https://clickhouse.com/docs/guides/developer/deduplication)).
- ReplacingMergeTree keyed on a download id: deduplication happens only during merges, so duplicates can persist ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- Query-time: `FINAL`, or `GROUP BY` with an aggregate, which that page says can be more efficient than `FINAL` ([deduplication](https://clickhouse.com/docs/guides/developer/deduplication)); `FINAL` has overhead, most visible when you do not filter on key columns ([ReplacingMergeTree guide](https://clickhouse.com/docs/guides/replacing-merge-tree)).

Tradeoff: ReplacingMergeTree offers eventual correctness only ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)); exact counts always pay at query time.

```sql
-- illustrative
CREATE TABLE downloads (download_id UUID, episode_id UInt64, ts DateTime, ip_hash UInt64)
ENGINE = ReplacingMergeTree ORDER BY (episode_id, download_id);
SELECT episode_id, count() FROM downloads FINAL WHERE episode_id = 42 GROUP BY episode_id;
```

### Scenario 6. Re-running the detector rewrites old confidence scores

Problem: a better model changes `confidence` for old episodes; avoid heavy rewrites.

Approach:
- Treat the re-run as new row versions, not updates: ReplacingMergeTree keeps, per sorting key, the row with the highest `ver`, so the re-run inserts rows with a larger version and the old ones disappear at merge ([ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)).
- The docs' own update pattern is "insert a new copy with a higher version" ([ReplacingMergeTree guide](https://clickhouse.com/docs/guides/replacing-merge-tree)).
- Keep `confidence` out of the sorting key, since mutations cannot update key columns ([mutations](https://clickhouse.com/docs/guides/developer/mutations)).
- The reason to avoid `ALTER ... UPDATE` at scale: the heavyweight form recreates all affected parts ([lightweight DELETE](https://clickhouse.com/docs/sql-reference/statements/delete) says this of heavyweight deletes), and the mutations page steers frequent changes toward deduplication ([mutations](https://clickhouse.com/docs/guides/developer/mutations)).
- Rollups built from the old scores need rebuilding or compensating rows.

Tradeoff: reads must use `FINAL` (or an aggregate over versions) to be correct before merges complete ([ReplacingMergeTree guide](https://clickhouse.com/docs/guides/replacing-merge-tree)), and materialized-view rollups do not see the replacement as a correction.

```sql
-- illustrative
CREATE TABLE mentions_v (episode_id UInt64, brand_id UInt32, confidence Float32, model_ver UInt32)
ENGINE = ReplacingMergeTree(model_ver) ORDER BY (episode_id, brand_id);
```

### Scenario 7. Transcript segments from Kafka in near real time

Problem: design the ingestion path and locate where batching happens.

Approach:
- Kafka table engine plus a materialized view into a MergeTree table; the engine acts as a stream, and the view receives new records in blocks and writes them to the target ([Kafka engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- Batching happens in the consumer: messages are grouped into blocks sized by `max_insert_block_size`, and if a block does not fill within `stream_flush_interval_ms` it is flushed anyway; `kafka_max_block_size` and `kafka_flush_interval_ms` tune this ([Kafka engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- Each flushed block becomes a part, which is why insert batching matters ([insert strategy](https://clickhouse.com/docs/best-practices/selecting-an-insert-strategy)).
- Durability: the docs warn the engine can silently lose consumed rows if the OS page cache is lost, and recommend `fsync_after_insert = 1` and `fsync_part_directory = 1` on target tables ([Kafka engine](https://clickhouse.com/docs/engines/table-engines/integrations/kafka)).
- A Go consumer that batches and inserts is the alternative if I want control over retries.

Tradeoff: smaller flush intervals lower latency but create more small parts; fsync settings buy durability at write cost.

```sql
-- illustrative
CREATE TABLE seg_queue (episode_id UInt64, start_ms UInt32, text String)
ENGINE = Kafka SETTINGS kafka_broker_list='...', kafka_topic_list='segments',
  kafka_group_name='ch', kafka_format='JSONEachRow';
CREATE MATERIALIZED VIEW seg_mv TO segments AS SELECT * FROM seg_queue;
```

### Scenario 8. Many small producers each inserting a few rows

Problem: Go and Node services insert a handful of rows at a time.

Approach:
- What goes wrong is part explosion: a synchronous insert immediately creates a part, and many small synchronous batches create many parts and heavy merge load ([insert strategy](https://clickhouse.com/docs/best-practices/selecting-an-insert-strategy)); too many parts can make ClickHouse reject inserts ([choosing a partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)).
- First fix, batch on the client: the docs recommend at least 1,000 rows and ideally 10,000-100,000 per insert, and about one insert per second ([insert strategy](https://clickhouse.com/docs/best-practices/selecting-an-insert-strategy)).
- Otherwise enable async inserts, where the server buffers and flushes on size (10 MiB default self-managed, 100 MiB on ClickHouse Cloud), time or query count (450 default) ([asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts), [settings reference](https://clickhouse.com/docs/reference/settings/session-settings/async-insert)).
- Or put a queue in front and consume in batches (Scenario 7).
- Use `async_insert=1,wait_for_async_insert=1`; the docs call `wait_for_async_insert=0` very risky because errors are not returned to the client ([insert strategy](https://clickhouse.com/docs/best-practices/selecting-an-insert-strategy)).

Tradeoff: async inserts add buffering delay, data is not queryable until flushed, and one bad row fails the whole query's data at flush ([asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)).

```sql
-- illustrative: per-connection settings from a small producer
INSERT INTO mentions SETTINGS async_insert=1, wait_for_async_insert=1 VALUES (...);
```

### Scenario 9. Campaign attribution inside flight windows

Problem: count mentions and downloads per campaign, only inside each campaign's start and end dates.

Approach:
- Campaigns are small and change slowly, so keep a copy of the flight table in ClickHouse and enrich at query time.
- Option A, dictionary: `range_hashed` supports lookups by key plus a date range, and `dictGet(dict, attr, id, date)` returns the value for the range containing the date ([dictionary layouts](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts/overview), [range_hashed](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts/range-hashed)).
- It returns one match per key and date, with `range_lookup_strategy` choosing among overlapping ranges, so it suits "which campaign owns this brand on this day" only when campaigns do not overlap.
- Option B, JOIN, for overlapping campaigns: join mentions to the campaigns table on brand and filter on the window; the docs advise filtering both inputs before the join and note that if the right table fits in memory the hash algorithm applies ([minimize and optimize JOINs](https://clickhouse.com/docs/best-practices/minimize-optimize-joins)).
- `ASOF JOIN` gives at most one right row per left row ([joining tables](https://clickhouse.com/docs/guides/joining-tables)), so it is the wrong tool for overlapping flights.
- Dictionaries are described as easier and more efficient than a JOIN with reference tables ([dictionaries](https://clickhouse.com/docs/sql-reference/dictionaries)).

Tradeoff: the dictionary is fast but cannot express overlap; the JOIN is general but costs memory on the right side.

```sql
-- illustrative
SELECT dictGet('campaign_flights', 'campaign_id', toUInt64(brand_id), mention_date) AS campaign_id,
       count() FROM mentions GROUP BY campaign_id;
```

### Scenario 10. Brand and podcast renames and category changes

Problem: dimension attributes change; queries must stay usable.

Approach:
- Keep names and categories out of the fact rows and look them up.
- A dictionary with a Postgres or ClickHouse source refreshes on `LIFETIME`; with a MIN/MAX range the server picks a random time in the window, a failed refresh leaves queries on the old copy, and `update_field` reloads only changed rows ([dictionary lifetime](https://clickhouse.com/docs/reference/statements/create/dictionary/lifetime), [dictionaries](https://clickhouse.com/docs/sql-reference/dictionaries)).
- Layout choice: `flat` is fastest but needs bounded `UInt64` keys, `hashed` has no key-size limit, and caching layouts are "Not recommended for latency-sensitive workloads or reliable insert-time enrichment" ([dictionary layouts](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts/overview)).
- Denormalizing names into fact rows moves the join to insert time, but a change can mean re-inserting every affected row, so the docs say batch reloads are more common and advise against it for frequently updated data ([denormalization](https://clickhouse.com/docs/data-modeling/denormalization)).
- Compromise: store stable ids in facts, look up current names with `dictGet`.

Tradeoff: query-time lookup always shows the current name, so a report over history relabels old data; if I want "name at the time", I must denormalize or use a date-ranged dictionary ([range_hashed](https://clickhouse.com/docs/reference/statements/create/dictionary/layouts/range-hashed)).

```sql
-- illustrative
SELECT dictGet('brands', 'name', brand_id) AS brand, count() FROM mentions GROUP BY brand;
```

### Scenario 11. Find every transcript segment containing a phrase

Problem: locate segments containing a given phrase, across a large text column.

Approach:
- Use a text index on the segment column; the skipping-index docs call it the recommended choice for full-text search and mark `tokenbf_v1` and `ngrambf_v1` as deprecated in its favour ([skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)).
- The text index is GA from version 26.2; `hasAllTokens` and `hasAnyTokens` match tokens using the index tokenizer, and `hasPhrase` matches consecutive ordered tokens and works without any flag ([text indexes](https://clickhouse.com/docs/engines/table-engines/mergetree-family/textindexes)). Without `support_phrase_search` it uses the index as a hint and verifies each surviving row; `support_phrase_search = 1` is experimental (it needs the MergeTree setting `allow_experimental_text_index_phrase_search`) and turns on exact index-only reads.
- Existing data needs `ALTER TABLE ... MATERIALIZE INDEX`, since skip indexes normally apply only to new inserts ([skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)).
- Limits: materializing text indexes with very many tokens can use significant memory, and parts above about 4.2 billion rows cannot be indexed ([text indexes](https://clickhouse.com/docs/engines/table-engines/mergetree-family/textindexes)).
- Search engine: my judgment, not a docs claim. The pages I read describe token and phrase matching, not relevance ranking or stemming, so if I needed those I would add a search engine beside ClickHouse.

Tradeoff: the index costs ingest work and storage ([skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)), and index-only phrase reads depend on an experimental flag.

```sql
-- illustrative
ALTER TABLE segments ADD INDEX txt text TYPE text(tokenizer = splitByNonAlpha);
SELECT episode_id, start_ms FROM segments WHERE hasAllTokens(text, 'acme shoes');
```

### Scenario 12. Retention: transcripts 90 days, events 2 years, rollups forever

Problem: different lifetimes for different tables.

Approach:
- One table per lifetime, each with its own TTL, and no TTL on rollups.
- Table TTL deletes expired rows, evaluated during background merges and not at insert time, so expired rows can stay visible for a while ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)); `merge_with_ttl_timeout` defaults to 14400 seconds ([TTL guide](https://clickhouse.com/docs/guides/developer/ttl)).
- Partition by the same date field used in the TTL expression so expired data can be dropped as whole partitions, which the TTL guide calls much cheaper than rewriting parts.
- Partition drops are metadata-level operations ([partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)), and `DROP PARTITION` removes data approximately 10 minutes after tagging ([partition operations](https://clickhouse.com/docs/sql-reference/statements/alter/partition)).
- Tiering: TTL `TO VOLUME` or `TO DISK` moves data between tiers defined in server configuration; the TTL guide flags that lesson as not supported in ClickHouse Cloud and says you do not need to move old data around there ([TTL guide](https://clickhouse.com/docs/guides/developer/ttl)); recent partitions can stay on fast storage while older ones go to cheaper storage ([partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)).

Tradeoff: rollups outlive the raw data, so they cannot be rebuilt after raw rows expire.

```sql
-- illustrative
CREATE TABLE segments (episode_id UInt64, ts DateTime, text String)
ENGINE = MergeTree PARTITION BY toYYYYMM(ts) ORDER BY (episode_id, ts)
TTL ts + INTERVAL 90 DAY DELETE;
```

### Scenario 13. Deleting all data for one podcast

Problem: a customer wants one podcast's data gone.

Approach:
- Lightweight `DELETE FROM ... WHERE podcast_id = X`: a mutation that hides rows through a hidden `_row_exists` mask, so queries stop returning them at once, with physical removal at a later merge ([DELETE](https://clickhouse.com/docs/sql-reference/statements/delete)).
- The heavyweight `ALTER TABLE ... DELETE` recreates all affected parts ([DELETE](https://clickhouse.com/docs/sql-reference/statements/delete)).
- If a month range is known, `DELETE IN PARTITION` limits the mutation to one partition ([partition operations](https://clickhouse.com/docs/sql-reference/statements/alter/partition)).
- Partition design: partitioning per podcast would make deletion a partition drop, but the docs recommend fewer than 100-1,000 distinct values and warn that high cardinality leaves many unmerged parts ([partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)), so I would not do it.
- Remember to delete from raw tables and any rollup keyed by podcast; rollups with only aggregate states may need rebuilding.
- Tables with projections are a limitation, since lightweight delete does not work on them by default ([DELETE](https://clickhouse.com/docs/sql-reference/statements/delete), [projections](https://clickhouse.com/docs/data-modeling/projections)).

Tradeoff: deletion is not immediate on disk, and heavy where clauses, long mutation queues or many parts slow it ([DELETE](https://clickhouse.com/docs/sql-reference/statements/delete)).

```sql
-- illustrative
DELETE FROM mentions WHERE podcast_id = 42;
```

### Scenario 14. Time-only filter on a table ordered by (brand_id, time)

Problem: a query filtering only on time is slow.

Approach:
- Diagnose with `EXPLAIN indexes = 1`, which shows per index the granules remaining after and before it is applied, including the primary key search algorithm; the docs note that from v25.9 it "only shows reasonable output when used with SETTINGS use_query_condition_cache = 0, use_skip_indexes_on_data_read = 0" ([EXPLAIN](https://clickhouse.com/docs/sql-reference/statements/explain)).
- Expect a generic exclusion search with little pruning: filtering on a later key column is only effective when the preceding column has lower cardinality ([sparse primary indexes](https://clickhouse.com/docs/guides/best-practices/sparse-primary-indexes)).
- Fix 1, partition pruning: if the table is partitioned by month the automatic MinMax index on the partition column can skip whole partitions ([partitioning key](https://clickhouse.com/docs/best-practices/choosing-a-partitioning-key)).
- Fix 2, a projection with time-first order, which is chosen automatically; fix 3, a second table fed by a materialized view, which must be queried explicitly ([projections](https://clickhouse.com/docs/data-modeling/projections)).
- A skip index helps only when the indexed value correlates with the primary key ([skipping indexes](https://clickhouse.com/docs/optimize/skipping-indexes)); time is only loosely correlated with `brand_id` order here, so `minmax` on time is unlikely to help.

Tradeoff: each added ordering duplicates storage and insert work.

```sql
-- illustrative
EXPLAIN indexes = 1 SELECT count() FROM mentions WHERE mention_ts >= now() - INTERVAL 1 DAY
SETTINGS use_query_condition_cache = 0, use_skip_indexes_on_data_read = 0;
```

### Scenario 15. Scale out: replicas, shards, sharding key

Problem: decide between adding replicas or shards, and what Distributed tables do to joins and distinct counts.

Approach:
- Replicas add copies of the same data; shards split it, and replication is independent per shard ([data replication](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication)). Add replicas for availability and read concurrency; add shards when one node's data or write volume is too large (my framing of the docs' split between the two).
- A Distributed table needs a sharding key, any integer expression, with `rand()` for even spread; keying by a column keeps that column's values on one shard ([Distributed](https://clickhouse.com/docs/engines/table-engines/special/distributed)).
- Mentions and downloads both join through `podcast_id`/`episode_id`, so I would shard both by the same key; the docs then allow local `IN` or `JOIN` instead of `GLOBAL` ones ([Distributed](https://clickhouse.com/docs/engines/table-engines/special/distributed)).
- Without colocation, regular `IN` on distributed subqueries multiplies requests and `GLOBAL IN` ships temporary tables to every server ([IN operators](https://clickhouse.com/docs/sql-reference/operators/in)).
- For distinct counts, aggregation runs on shards and intermediate results are merged at the initiator ([Distributed](https://clickhouse.com/docs/engines/table-engines/special/distributed)); `uniqCombined` can help when many states cross the network ([uniqCombined](https://clickhouse.com/docs/sql-reference/aggregate-functions/reference/uniqcombined)). Set `internal_replication` to true with replicated engines.

Tradeoff: one sharding key favours one join pattern, and distributed inserts are written in the background first, so a node failure can lose data not yet forwarded ([Distributed](https://clickhouse.com/docs/engines/table-engines/special/distributed)).

```sql
-- illustrative
CREATE TABLE mentions_all AS mentions_local
ENGINE = Distributed(cluster, currentDatabase(), mentions_local, podcast_id);
```

### Scenario 16. What a reader sees right after an insert on a replicated cluster

Problem: reason about read-your-writes across replicas and which settings buy stronger guarantees.

Approach:
- Replication is asynchronous and multi-master, inserts can go to any server, and data reaches the other replicas with some latency; by default an INSERT waits for confirmation from only one replica ([data replication](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replication)). So a read from another replica can miss the row.
- Write side: `insert_quorum` (default 0; 2 or more enables it; `'auto'` means a majority) makes the insert succeed only when enough replicas have the data, with `insert_quorum_timeout` defaulting to 600000 ms ([insert_quorum settings](https://clickhouse.com/docs/reference/settings/session-settings/insert-quorum)).
- Read side: `select_sequential_consistency` restricts SELECTs to replicas holding all previous quorum inserts, and does not work while `insert_quorum_parallel` (default enabled) is on ([other session settings](https://clickhouse.com/docs/reference/settings/session-settings/other)).
- With async inserts, the data is also invisible until the buffer flushes, and `wait_for_async_insert=1` acknowledges only after the flush ([asynchronous inserts](https://clickhouse.com/docs/optimize/asynchronous-inserts)).

Tradeoff: quorum writes add latency and can fail on timeout, and sequential consistency forces serial quorum inserts; dashboards that tolerate seconds of staleness should stay on defaults.

```sql
-- illustrative
INSERT INTO downloads SETTINGS insert_quorum = 'auto', insert_quorum_parallel = 0 VALUES (...);
SELECT count() FROM downloads SETTINGS select_sequential_consistency = 1;
```

### Scenario 17. What should not live in ClickHouse, and keeping Postgres in sync

Problem: accounts, campaign configuration and billing versus the event data.

Approach:
- Keep accounts, campaign configuration and billing in Postgres; ClickHouse holds events, transcripts and rollups.
- The reasoning from the docs is about update shape: row changes in MergeTree are mutations or merge-time version replacement ([mutations](https://clickhouse.com/docs/guides/developer/mutations), [ReplacingMergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/replacingmergetree)), and the denormalization page advises against frequently updated data ([denormalization](https://clickhouse.com/docs/data-modeling/denormalization)).
- Sync option 1: a dictionary with a PostgreSQL source for small reference tables such as campaigns and brands, refreshed by `LIFETIME` ([dictionaries](https://clickhouse.com/docs/sql-reference/dictionaries), [dictionary lifetime](https://clickhouse.com/docs/reference/statements/create/dictionary/lifetime)).
- Sync option 2: CDC into ClickHouse, which in ClickPipes creates ReplacingMergeTree tables where updates and deletes arrive as new row versions, read with `FINAL` and `_peerdb_is_deleted = 0` ([Postgres ClickPipe](https://clickhouse.com/docs/integrations/clickpipes/postgres)).
- That is a Cloud product; for self-managed I did not find a docs-backed equivalent in the pages I read.

Tradeoff: changes arrive in batches (the ClickPipe default interval is 60 seconds), so ClickHouse is briefly behind Postgres ([Postgres ClickPipe](https://clickhouse.com/docs/integrations/clickpipes/postgres)).

```sql
-- illustrative: current campaign state from the CDC table
SELECT * FROM campaigns FINAL WHERE _peerdb_is_deleted = 0;
```

### Scenario 18. A download log arrives two days late

Problem: late, out-of-order events; see what breaks and what holds.

Approach:
- Partition by event date, so late rows land in the old partition as a new part; merging happens within a partition, which keeps ReplacingMergeTree deduplication working as long as a row's partition never changes ([ReplacingMergeTree guide](https://clickhouse.com/docs/guides/replacing-merge-tree)).
- Materialized views are insert triggers over each block ([incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)), so late rows flow through them and update the right day's rollup row, as that page shows for per-day targets; no special backfill is needed.
- What can break, partition-level operations: a dropped or TTL-expired partition no longer matches data that arrives afterwards, and TTL is evaluated at merge on the row's own timestamp ([MergeTree](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)), so a row older than the retention window can be deleted soon after arrival (my inference from that rule).
- What can break, joins: changes to a joined right-side table do not retroactively update a materialized view ([incremental materialized views](https://clickhouse.com/docs/materialized-view/incremental-materialized-view)).
- What can break, cached results: refreshable views and cached dashboards show old numbers until the next refresh ([materialized view best practices](https://clickhouse.com/docs/best-practices/use-materialized-views)). Duplicates from a redelivered late batch fall back on Scenario 5.

Tradeoff: reports for the past two days change after the fact, so numbers are only final after a lateness window I must choose myself.

```sql
-- illustrative: partition by event time, not arrival time
CREATE TABLE downloads (event_ts DateTime, arrived_ts DateTime, episode_id UInt64)
ENGINE = MergeTree PARTITION BY toYYYYMM(event_ts) ORDER BY (episode_id, event_ts);
```
