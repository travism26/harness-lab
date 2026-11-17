"""Raw table versus rollup: the same question answered both ways.

For each pair: 1 warm-up run, 7 timed runs (client-side wall clock), server-side
read_rows/read_bytes from the X-ClickHouse-Summary header, and a check that both
answers are identical. Query cache is switched off per query.
--optimize-rollups first forces the rollup tables to merge fully, to separate
"fewer rows to read" from "rows not merged yet".
Schema: experiments/clickhouse-podcast-analytics/schema/02_rollups.sql
"""
import argparse
import statistics
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ch  # noqa: E402

RUNS = 7
# wait_end_of_query makes the summary header final (otherwise it is sent early).
SETTINGS = {"use_query_cache": 0, "wait_end_of_query": 1}
BRAND = 103  # most-mentioned brand in the default generated data

PAIRS = [
    ("a. one brand, mentions per day, 90 days",
     f"""SELECT toDate(mentioned_at) AS d, count() AS mentions
         FROM podcast.brand_mentions
         WHERE brand_id = {BRAND} AND toDate(mentioned_at) >= today() - 90
         GROUP BY d ORDER BY d FORMAT TSV""",
     f"""SELECT day AS d, sum(mentions) AS mentions
         FROM podcast.brand_mentions_daily
         WHERE brand_id = {BRAND} AND day >= today() - 90
         GROUP BY d ORDER BY d FORMAT TSV"""),
    ("b. top 10 brands per week, all data",
     """SELECT week, brand_id, c FROM (
            SELECT toStartOfWeek(mentioned_at) AS week, brand_id, count() AS c,
                   row_number() OVER (PARTITION BY week ORDER BY count() DESC, brand_id) AS r
            FROM podcast.brand_mentions GROUP BY week, brand_id)
        WHERE r <= 10 ORDER BY week, r FORMAT TSV""",
     """SELECT week, brand_id, c FROM (
            SELECT toStartOfWeek(day) AS week, brand_id, sum(mentions) AS c,
                   row_number() OVER (PARTITION BY week ORDER BY sum(mentions) DESC, brand_id) AS r
            FROM podcast.brand_mentions_daily GROUP BY week, brand_id)
        WHERE r <= 10 ORDER BY week, r FORMAT TSV"""),
    ("c. share of voice per week",
     """SELECT week, brand_id, c, round(100 * c / sum(c) OVER (PARTITION BY week), 6) AS pct
        FROM (SELECT toStartOfWeek(mentioned_at) AS week, brand_id, count() AS c
              FROM podcast.brand_mentions GROUP BY week, brand_id)
        ORDER BY week, brand_id FORMAT TSV""",
     """SELECT week, brand_id, c, round(100 * c / sum(c) OVER (PARTITION BY week), 6) AS pct
        FROM (SELECT toStartOfWeek(day) AS week, brand_id, sum(mentions) AS c
              FROM podcast.brand_mentions_daily GROUP BY week, brand_id)
        ORDER BY week, brand_id FORMAT TSV"""),
    ("d. distinct episodes per brand per month",
     """SELECT toStartOfMonth(mentioned_at) AS m, brand_id, uniq(episode_id) AS episodes
        FROM podcast.brand_mentions GROUP BY m, brand_id ORDER BY m, brand_id FORMAT TSV""",
     """SELECT toStartOfMonth(day) AS m, brand_id, uniqMerge(episodes) AS episodes
        FROM podcast.brand_mentions_daily GROUP BY m, brand_id ORDER BY m, brand_id FORMAT TSV"""),
    ("e. deduplicated downloads per region per day",
     """SELECT toDate(downloaded_at) AS d, region, uniq(download_id) AS downloads
        FROM podcast.downloads GROUP BY d, region ORDER BY d, region FORMAT TSV""",
     """SELECT day AS d, region, uniqMerge(downloads) AS downloads
        FROM podcast.downloads_daily GROUP BY d, region ORDER BY d, region FORMAT TSV"""),
]

ROLLUPS = ["brand_mentions_daily", "downloads_daily"]
TABLES = ["podcasts", "episodes", "brands", "campaigns", "transcript_segments",
          "brand_mentions", "downloads", "brand_mentions_daily", "downloads_daily"]


def part_counts():
    r = ch.rows("SELECT table, count() FROM system.parts WHERE database = 'podcast' AND active "
                "GROUP BY table ORDER BY table")
    return {t: int(n) for t, n in r}


def wait_for_merges(max_wait=90):
    """Poll until part counts are unchanged for 3 checks and no merge is running."""
    prev, stable, waited = None, 0, 0
    while waited <= max_wait:
        cur = part_counts()
        running = int(ch.rows("SELECT count() FROM system.merges WHERE database = 'podcast'")[0][0])
        stable = stable + 1 if (cur == prev and running == 0) else 0
        prev = cur
        if stable >= 3:
            return cur, True, waited
        time.sleep(3)
        waited += 3
    return prev, False, waited


def timed(sql):
    t0 = time.perf_counter()
    body, summary = ch.query(sql, **SETTINGS)
    return (time.perf_counter() - t0) * 1000, body, summary


def bench(sql):
    timed(sql)  # warm-up
    times, body, summary = [], "", {}
    for _ in range(RUNS):
        ms, body, summary = timed(sql)
        times.append(ms)
    return statistics.median(times), min(times), summary, body


def compare(raw_body, roll_body):
    a, b = Counter(raw_body.splitlines()), Counter(roll_body.splitlines())
    diff = (a - b) + (b - a)
    return sum(diff.values()), sum(a.values()), diff, a, b


def human(n):
    for u in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} TiB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--optimize-rollups", action="store_true",
                    help="OPTIMIZE ... FINAL the rollup tables before timing")
    a = ap.parse_args()
    print("server version:", ch.rows("SELECT version()")[0][0])
    if a.optimize_rollups:
        for t in ROLLUPS:
            ch.query(f"OPTIMIZE TABLE podcast.{t} FINAL")
        print("rollups fully merged with OPTIMIZE ... FINAL")
    print("\nrow counts:")
    for t in TABLES:
        print(f"  {t:22s} {int(ch.rows(f'SELECT count() FROM podcast.{t}')[0][0]):>10,}")
    print("\non-disk size (active parts):")
    for t, rows_, comp, unc in ch.rows(
            "SELECT table, sum(rows), sum(data_compressed_bytes), sum(data_uncompressed_bytes) "
            "FROM system.parts WHERE database = 'podcast' AND active GROUP BY table ORDER BY table"):
        print(f"  {t:22s} rows {int(rows_):>10,}  compressed {human(int(comp)):>10}  "
              f"uncompressed {human(int(unc)):>10}")
    try:
        r = ch.rows("SELECT name, sum(rows), sum(data_compressed_bytes) FROM system.projection_parts "
                    "WHERE database = 'podcast' AND active GROUP BY name")
        for n, rows_, comp in r:
            print(f"  projection {n}: rows {int(rows_):,}, compressed {human(int(comp))}")
    except ch.ClickHouseError as e:
        print("  (projection sizes unavailable:", str(e).splitlines()[0], ")")

    counts, settled, waited = wait_for_merges()
    print(f"\nbackground merges settled: {settled} (waited {waited}s); active parts per table:")
    print("  " + ", ".join(f"{t}={n}" for t, n in counts.items()))

    results, notes = [], []
    for name, raw_sql, roll_sql in PAIRS:
        rm, rmin, rs, rb = bench(raw_sql)
        cm, cmin, cs, cb = bench(roll_sql)
        n_diff, n_rows, diff, a, b = compare(rb, cb)
        status = "MATCH" if n_diff == 0 else f"DIFF ({n_diff} differing lines of {n_rows})"
        print(f"{name}: {status}")
        if n_diff:
            for line, c in list(diff.items())[:5]:
                side = "raw only" if a[line] > b[line] else "rollup only"
                notes.append(f"  {name} [{side}] {line}")
        results.append((name, rm, rmin, rs, cm, cmin, cs, status))
    for n in notes:
        print(n)

    print("\n| pair | raw median ms | raw min ms | raw read_rows | raw read_bytes "
          "| rollup median ms | rollup min ms | rollup read_rows | rollup read_bytes | result |")
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for name, rm, rmin, rs, cm, cmin, cs, status in results:
        print(f"| {name} | {rm:.1f} | {rmin:.1f} | {rs.get('read_rows', 0):,} | {human(rs.get('read_bytes', 0))} "
              f"| {cm:.1f} | {cmin:.1f} | {cs.get('read_rows', 0):,} | {human(cs.get('read_bytes', 0))} | {status} |")


if __name__ == "__main__":
    main()
