-- Top 10 brands per week, read from the daily rollup (not the raw mentions).
-- Shows: re-aggregating a rollup with sum() + GROUP BY, ranking with a window
-- function, and dictGet on podcast.brands_dict instead of a JOIN for names.
-- Only the latest 3 weeks are printed; the first week of data may be partial.
SELECT week, rank, brand, industry, weekly_mentions
FROM
(
    SELECT
        toStartOfWeek(day) AS week,
        dictGet('podcast.brands_dict', 'name', toUInt64(brand_id)) AS brand,
        dictGet('podcast.brands_dict', 'industry', toUInt64(brand_id)) AS industry,
        sum(mentions) AS weekly_mentions,
        row_number() OVER (PARTITION BY week ORDER BY weekly_mentions DESC) AS rank
    FROM podcast.brand_mentions_daily
    GROUP BY week, brand_id
)
WHERE rank <= 10
  AND week >= (SELECT max(toStartOfWeek(day)) FROM podcast.brand_mentions_daily) - INTERVAL 14 DAY
ORDER BY week DESC, rank;
