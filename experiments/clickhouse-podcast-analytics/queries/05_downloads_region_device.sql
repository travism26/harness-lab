-- Downloads by region and device for the top 5 podcasts, on the raw table.
-- Shows: filtering on podcast_id, the leading primary-key column, so only the
-- matching granules are read for the outer query. The top-5 subquery does scan
-- the whole table once. uniqExact(download_id) ignores redelivered duplicates.
SELECT
    podcast_id,
    region,
    device,
    uniqExact(download_id) AS downloads
FROM podcast.downloads
WHERE podcast_id IN
(
    SELECT podcast_id FROM podcast.downloads
    GROUP BY podcast_id ORDER BY uniqExact(download_id) DESC LIMIT 5
)
GROUP BY podcast_id, region, device
ORDER BY podcast_id, downloads DESC
LIMIT 3 BY podcast_id;
