-- Brand drill-down on the raw mentions table: one brand, last 30 days, by day and
-- mention_type. The sort key (brand_id, mentioned_at, podcast_id) serves it.
-- Then a podcast-first lookup that the by_podcast projection should serve, with
-- EXPLAIN indexes = 1 to show which projection was chosen (or not).
-- Brand 103 and podcast 1372 are the busiest ones for the generator's default seed.
SELECT toDate(mentioned_at) AS day, mention_type, count() AS mentions
FROM podcast.brand_mentions
WHERE brand_id = 103 AND mentioned_at >= now() - INTERVAL 30 DAY
GROUP BY day, mention_type
ORDER BY day DESC, mention_type
LIMIT 10;

EXPLAIN indexes = 1
SELECT toDate(mentioned_at) AS day, mention_type, count() AS mentions
FROM podcast.brand_mentions
WHERE brand_id = 103 AND mentioned_at >= now() - INTERVAL 30 DAY
GROUP BY day, mention_type;

SELECT toDate(mentioned_at) AS day, count() AS mentions, uniq(brand_id) AS brands
FROM podcast.brand_mentions
WHERE podcast_id = 1372 AND mentioned_at >= now() - INTERVAL 7 DAY
GROUP BY day
ORDER BY day DESC;

EXPLAIN indexes = 1
SELECT toDate(mentioned_at) AS day, count() AS mentions, uniq(brand_id) AS brands
FROM podcast.brand_mentions
WHERE podcast_id = 1372 AND mentioned_at >= now() - INTERVAL 7 DAY
GROUP BY day;
