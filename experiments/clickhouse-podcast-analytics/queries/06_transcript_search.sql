-- Transcript search: segments that contain a brand name as a whole token, using
-- hasToken, which the text index (tokenizer splitByNonAlpha) can serve.
-- Then EXPLAIN indexes = 1 for a present token and an absent one, to see whether
-- the skip index is used and how many parts/granules it drops.
SELECT podcast_id, episode_id, segment_idx, text
FROM podcast.transcript_segments
WHERE hasToken(text, 'Taworiji')
ORDER BY episode_id, segment_idx
LIMIT 5;

SELECT count() AS segments_with_token FROM podcast.transcript_segments WHERE hasToken(text, 'Taworiji');

-- A bare count() is answered straight from the index ("ReadFromTextIndexCount"),
-- which hides the skip statistics, so count distinct episodes instead.
EXPLAIN indexes = 1
SELECT uniq(episode_id) FROM podcast.transcript_segments WHERE hasToken(text, 'Taworiji');

-- Token that never occurs: the index should rule out whole parts.
EXPLAIN indexes = 1
SELECT count() FROM podcast.transcript_segments WHERE hasToken(text, 'Nosuchbrand');
