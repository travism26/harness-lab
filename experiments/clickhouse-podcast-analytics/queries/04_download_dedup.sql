-- Four ways to count one month of downloads (last full month), raw to strict:
-- raw count(), count() FINAL (ReplacingMergeTree dedup), uniqExact(download_id),
-- and one download per listener per episode per day.
-- Expect raw >= final = distinct ids >= listener-episode-day. Raw can equal FINAL
-- once background merges have removed the redelivered duplicates.
SELECT
    count() AS raw_rows,
    (SELECT count() FROM podcast.downloads FINAL
     WHERE downloaded_at >= toStartOfMonth(now() - INTERVAL 1 MONTH) AND downloaded_at < toStartOfMonth(now())) AS after_final,
    uniqExact(download_id) AS distinct_download_ids,
    uniqExact(listener_hash, episode_id, toDate(downloaded_at)) AS listener_episode_days
FROM podcast.downloads
WHERE downloaded_at >= toStartOfMonth(now() - INTERVAL 1 MONTH) AND downloaded_at < toStartOfMonth(now());
