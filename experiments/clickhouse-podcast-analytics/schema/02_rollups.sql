-- Rollup targets and the materialized views that feed them.
-- Merges are eventual, so queries must re-aggregate (sum, uniqMerge) with GROUP BY.

CREATE TABLE IF NOT EXISTS podcast.brand_mentions_daily
(
    day                       Date,
    brand_id                  UInt32,
    mentions                  SimpleAggregateFunction(sum, UInt64),
    high_confidence_mentions  SimpleAggregateFunction(sum, UInt64),
    confidence_sum            SimpleAggregateFunction(sum, Float64),
    episodes                  AggregateFunction(uniq, UInt64),
    podcasts                  AggregateFunction(uniq, UInt32)
)
ENGINE = AggregatingMergeTree
ORDER BY (day, brand_id);

CREATE MATERIALIZED VIEW IF NOT EXISTS podcast.brand_mentions_daily_mv
TO podcast.brand_mentions_daily AS
SELECT
    toDate(mentioned_at)               AS day,
    brand_id,
    count()                            AS mentions,
    countIf(confidence >= 0.8)         AS high_confidence_mentions,
    sum(toFloat64(confidence))         AS confidence_sum,
    uniqState(episode_id)              AS episodes,
    uniqState(podcast_id)              AS podcasts
FROM podcast.brand_mentions
GROUP BY day, brand_id;

-- A materialized view sees every inserted block, including redelivered
-- duplicates that ReplacingMergeTree removes later. So the rollup keeps a
-- distinct-count state over download_id instead of a plain count.
CREATE TABLE IF NOT EXISTS podcast.downloads_daily
(
    day               Date,
    region            LowCardinality(String),
    device            LowCardinality(String),
    downloads         AggregateFunction(uniq, UUID),
    listener_episodes AggregateFunction(uniq, UInt64, UInt64)
)
ENGINE = AggregatingMergeTree
ORDER BY (day, region, device);

CREATE MATERIALIZED VIEW IF NOT EXISTS podcast.downloads_daily_mv
TO podcast.downloads_daily AS
SELECT
    toDate(downloaded_at)                    AS day,
    region,
    device,
    uniqState(download_id)                   AS downloads,
    uniqState(listener_hash, episode_id)     AS listener_episodes
FROM podcast.downloads
GROUP BY day, region, device;
