-- Mentions per campaign window: total mentions of the campaign's brand inside
-- start_date..end_date, and the daily average inside versus outside the window.
-- Shows: joining a small dimension to the daily rollup. Days with no mentions
-- have no rollup row, so averages divide by calendar days, not by rows.
WITH
    (SELECT max(day) - min(day) + 1 FROM podcast.brand_mentions_daily) AS span_days,
    daily AS (SELECT day, brand_id, sum(mentions) AS m FROM podcast.brand_mentions_daily GROUP BY day, brand_id)
SELECT
    c.campaign_id,
    dictGet('podcast.brands_dict', 'name', toUInt64(c.brand_id)) AS brand,
    c.start_date,
    c.end_date,
    sumIf(d.m, d.day BETWEEN c.start_date AND c.end_date) AS mentions_in_window,
    round(mentions_in_window / (c.end_date - c.start_date + 1), 1) AS avg_per_day_inside,
    round(sumIf(d.m, d.day NOT BETWEEN c.start_date AND c.end_date)
          / (span_days - (c.end_date - c.start_date + 1)), 1) AS avg_per_day_outside,
    round(avg_per_day_inside / avg_per_day_outside, 2) AS lift
FROM podcast.campaigns AS c
LEFT JOIN daily AS d ON d.brand_id = c.brand_id
GROUP BY c.campaign_id, c.brand_id, c.start_date, c.end_date
ORDER BY mentions_in_window DESC
LIMIT 15;
