-- Podcast ad measurement: dimensions, dictionary and raw fact tables.
-- Rollups live in experiments/clickhouse-podcast-analytics/schema/02_rollups.sql.
CREATE DATABASE IF NOT EXISTS podcast;

-- Dimensions: small, so plain MergeTree keyed on the lookup id.
CREATE TABLE IF NOT EXISTS podcast.podcasts
(
    podcast_id UInt32,
    title      String,
    publisher  LowCardinality(String),
    category   LowCardinality(String),
    language   LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY podcast_id;

CREATE TABLE IF NOT EXISTS podcast.episodes
(
    episode_id   UInt64,
    podcast_id   UInt32,
    title        String,
    published_at DateTime,
    duration_s   UInt32
)
ENGINE = MergeTree
ORDER BY (podcast_id, episode_id);

CREATE TABLE IF NOT EXISTS podcast.brands
(
    brand_id UInt32,
    name     String,
    industry LowCardinality(String)
)
ENGINE = MergeTree
ORDER BY brand_id;

CREATE TABLE IF NOT EXISTS podcast.campaigns
(
    campaign_id UInt32,
    brand_id    UInt32,
    name        String,
    start_date  Date,
    end_date    Date
)
ENGINE = MergeTree
ORDER BY (brand_id, campaign_id);

-- FLAT layout: brand ids are small and dense, so lookups are array indexing.
-- Used with dictGet in queries instead of a JOIN.
CREATE DICTIONARY IF NOT EXISTS podcast.brands_dict
(
    brand_id UInt64,
    name     String,
    industry String
)
PRIMARY KEY brand_id
SOURCE(CLICKHOUSE(TABLE 'brands' DB 'podcast'))
LAYOUT(FLAT())
LIFETIME(MIN 300 MAX 600);

-- Facts.
-- Monthly partitions plus the 2-year TTL let whole months drop cheaply.
-- The text index (GA since 26.2) replaces tokenbf_v1, which the docs no longer
-- recommend for full-text search. It serves hasToken/hasAllTokens/hasAnyTokens.
CREATE TABLE IF NOT EXISTS podcast.transcript_segments
(
    podcast_id   UInt32,
    episode_id   UInt64,
    segment_idx  UInt32,
    start_ms     UInt32,
    end_ms       UInt32,
    published_at DateTime,
    text         String CODEC(ZSTD(3)),
    INDEX text_tokens text TYPE text(tokenizer = splitByNonAlpha)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(published_at)
ORDER BY (podcast_id, episode_id, segment_idx)
TTL published_at + INTERVAL 2 YEAR;

-- Brand leads the key: the main drill-down is "one brand over a date range".
-- Cross-brand time scans use the daily rollup; the projection serves
-- podcast-first lookups at the cost of storing the data twice.
CREATE TABLE IF NOT EXISTS podcast.brand_mentions
(
    mentioned_at     DateTime,
    brand_id         UInt32,
    podcast_id       UInt32,
    episode_id       UInt64,
    segment_idx      UInt32,
    offset_ms        UInt32,
    mention_type     LowCardinality(String),
    confidence       Float32,
    detector_version LowCardinality(String),
    PROJECTION by_podcast (SELECT * ORDER BY podcast_id, mentioned_at)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(mentioned_at)
ORDER BY (brand_id, mentioned_at, podcast_id);

-- The full sorting key ends in download_id: that is the row identity
-- ReplacingMergeTree dedups on. PRIMARY KEY is a shorter prefix so the
-- in-memory index stays small.
CREATE TABLE IF NOT EXISTS podcast.downloads
(
    downloaded_at DateTime,
    download_id   UUID,
    podcast_id    UInt32,
    episode_id    UInt64,
    region        LowCardinality(String),
    device        LowCardinality(String),
    listener_hash UInt64,
    bytes         UInt32,
    ingested_at   DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(ingested_at)
PARTITION BY toYYYYMM(downloaded_at)
PRIMARY KEY (podcast_id, episode_id)
ORDER BY (podcast_id, episode_id, download_id);
