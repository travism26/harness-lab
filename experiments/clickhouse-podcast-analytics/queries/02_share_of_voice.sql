-- Share of voice: each brand's share of all mentions in a week, and of its
-- industry's mentions that week, from the daily rollup.
-- Shows: window functions over a grouped result; the second statement checks
-- that the shares add up to 100 percent.
-- Uses the latest complete week (the week before the newest data's week).
WITH weekly AS
(
    SELECT
        toStartOfWeek(day) AS week,
        brand_id,
        dictGet('podcast.brands_dict', 'name', toUInt64(brand_id)) AS brand,
        dictGet('podcast.brands_dict', 'industry', toUInt64(brand_id)) AS industry,
        sum(mentions) AS mentions
    FROM podcast.brand_mentions_daily
    GROUP BY week, brand_id
    HAVING week = (SELECT max(toStartOfWeek(day)) FROM podcast.brand_mentions_daily) - INTERVAL 7 DAY
)
SELECT
    week, brand, industry, mentions,
    round(100 * mentions / sum(mentions) OVER (PARTITION BY week), 2) AS pct_of_all,
    round(100 * mentions / sum(mentions) OVER (PARTITION BY week, industry), 2) AS pct_of_industry
FROM weekly
ORDER BY mentions DESC
LIMIT 10;

SELECT
    week,
    round(sum(pct_of_all), 4) AS total_pct_all_brands
FROM
(
    SELECT
        toStartOfWeek(day) AS week,
        brand_id,
        100 * sum(mentions) / sum(sum(mentions)) OVER (PARTITION BY toStartOfWeek(day)) AS pct_of_all
    FROM podcast.brand_mentions_daily
    GROUP BY week, brand_id
)
GROUP BY week
ORDER BY week DESC
LIMIT 3;
