"""Synthetic podcast ad-measurement data, loaded over the ClickHouse HTTP interface.

Deterministic for a given --seed/--scale/--end-date. Re-running truncates every
table first, so row counts are the same each time.
Schema: experiments/clickhouse-podcast-analytics/schema/01_tables.sql
"""
import argparse
import datetime as dt
import random
import sys
import time
from bisect import bisect_left
from itertools import accumulate
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ch  # noqa: E402

BATCH = 100_000
DAYS = 180
N_PODCASTS = 2_000
N_EPISODES = 180_000
N_BRANDS = 200
N_CAMPAIGNS = 80
N_MENTIONS = 2_000_000
N_DOWNLOADS = 3_000_000  # distinct download_ids, redeliveries come on top
SEGMENT_SAMPLE = 0.05
SEGMENTS_PER_EPISODE = 25
SAME_DAY_REPEAT = 0.08
REDELIVER = 0.01

INDUSTRIES = ["auto", "banking", "beverage", "fashion", "food", "gaming",
              "health", "software", "telecom", "travel"]
CATEGORIES = ["news", "comedy", "tech", "sports", "true crime", "business",
              "health", "music", "education", "society"]
LANGS = ["en", "en", "en", "es", "de", "fr", "pt"]
REGIONS = ["US", "GB", "CA", "AU", "DE", "FR", "ES", "IT", "NL", "SE",
           "BR", "MX", "IN", "JP", "KR", "ZA", "NG", "PL", "IE", "NZ"]
DEVICES = ["iphone", "android", "desktop", "smart_speaker", "web_player", "car"]
DEVICE_W = [45, 30, 10, 6, 7, 2]
SYLL = ["ba", "ko", "ri", "ve", "lu", "mo", "ta", "ni", "sa", "do", "fe", "gi",
        "pu", "ze", "xa", "wo", "ha", "ji", "qu", "yo"]
WORDS = ("today we talk about the new season of local food markets and how people "
         "plan their week around small habits weather travel music sleep money "
         "tools phones games health cars coffee phones friends stories listeners "
         "question answer guest story long short quick simple honest great odd").split()


def zipf(n, s):
    return [1.0 / (r ** s) for r in range(1, n + 1)]


def flush(table, cols, lines, label, stats):
    t0 = time.time()
    n = 0
    for i in range(0, len(lines), BATCH):
        chunk = lines[i:i + BATCH]
        ch.insert(f"{table} ({cols})", "\n".join(chunk) + "\n")
        n += len(chunk)
    dt_s = time.time() - t0
    stats.append((label, n, dt_s))
    print(f"  {label}: {n:>9,} rows inserted in {dt_s:6.1f}s", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--scale", type=float, default=1.0,
                    help="multiplies mentions, downloads and transcript sample")
    ap.add_argument("--end-date", type=dt.date.fromisoformat, default=None)
    a = ap.parse_args()

    t_start = time.time()
    rng = random.Random(a.seed)
    rand = rng.random
    end_date = a.end_date or dt.date.today()
    start_date = end_date - dt.timedelta(days=DAYS - 1)
    epoch = dt.datetime(1970, 1, 1)
    start_ts = int((dt.datetime.combine(start_date, dt.time()) - epoch).total_seconds())
    end_ts = start_ts + DAYS * 86400
    n_mentions = int(N_MENTIONS * a.scale)
    n_downloads = int(N_DOWNLOADS * a.scale)
    print(f"window {start_date} .. {end_date}, seed {a.seed}, scale {a.scale}")

    for t in ["podcasts", "episodes", "brands", "campaigns", "transcript_segments",
              "brand_mentions", "downloads", "brand_mentions_daily", "downloads_daily"]:
        ch.query(f"TRUNCATE TABLE IF EXISTS podcast.{t}")
    stats = []

    # --- dimensions -------------------------------------------------------
    pod_w = zipf(N_PODCASTS, 0.6)
    rng.shuffle(pod_w)
    pods = []
    for i in range(1, N_PODCASTS + 1):
        pods.append(f"{i}\tPodcast {i}\tPublisher {rng.randrange(1, 300)}\t"
                    f"{rng.choice(CATEGORIES)}\t{rng.choice(LANGS)}")
    flush("podcast.podcasts", "podcast_id,title,publisher,category,language", pods, "podcasts", stats)

    brand_names, seen = [], set()
    while len(brand_names) < N_BRANDS:
        nm = "".join(rng.choice(SYLL) for _ in range(rng.choice((3, 4)))).capitalize()
        if nm not in seen:
            seen.add(nm)
            brand_names.append(nm)
    brand_w = zipf(N_BRANDS, 1.0)
    rng.shuffle(brand_w)
    brands = [f"{i + 1}\t{brand_names[i]}\t{INDUSTRIES[i % len(INDUSTRIES)]}" for i in range(N_BRANDS)]
    flush("podcast.brands", "brand_id,name,industry", brands, "brands", stats)
    ch.query("SYSTEM RELOAD DICTIONARY podcast.brands_dict")

    # Episodes sorted by publish time, so the episode index is also a time rank.
    ep_pub = sorted(rng.randrange(start_ts, end_ts - 3600) for _ in range(N_EPISODES))
    ep_pod = rng.choices(range(1, N_PODCASTS + 1), weights=pod_w, k=N_EPISODES)
    ep_dur = [rng.randrange(600, 5400) for _ in range(N_EPISODES)]
    eps = [f"{i + 1}\t{ep_pod[i]}\tEpisode {i + 1}\t{ep_pub[i]}\t{ep_dur[i]}" for i in range(N_EPISODES)]
    flush("podcast.episodes", "episode_id,podcast_id,title,published_at,duration_s", eps, "episodes", stats)
    ep_cum = list(accumulate(pod_w[p - 1] for p in ep_pod))

    # Campaigns: 14-60 days, fully inside the data window.
    camp_brands = rng.sample(range(1, N_BRANDS + 1), N_CAMPAIGNS)
    camps = []  # (brand, start_ts, end_ts_exclusive)
    camp_lines = []
    for i, b in enumerate(camp_brands, 1):
        length = rng.randint(14, 60)
        s = rng.randint(0, DAYS - length)
        c_start = start_date + dt.timedelta(days=s)
        c_end = c_start + dt.timedelta(days=length - 1)
        s_ts = start_ts + s * 86400
        camps.append((b, s_ts, s_ts + length * 86400))
        camp_lines.append(f"{i}\t{b}\tCampaign {i}\t{c_start}\t{c_end}")
    flush("podcast.campaigns", "campaign_id,brand_id,name,start_date,end_date", camp_lines, "campaigns", stats)

    # --- brand_mentions ---------------------------------------------------
    # 40% of mentions come from campaign windows (brand fixed, episodes published
    # inside the window); the rest follow overall brand and podcast popularity.
    n_c = int(n_mentions * 0.4)
    n_b = n_mentions - n_c
    brand_cum = list(accumulate(brand_w))
    b_brand = rng.choices(range(1, N_BRANDS + 1), cum_weights=brand_cum, k=n_b)
    b_ep = rng.choices(range(N_EPISODES), cum_weights=ep_cum, k=n_b)
    camp_w = [brand_w[b - 1] ** 0.5 for b, _, _ in camps]
    camp_pick = rng.choices(range(N_CAMPAIGNS), weights=camp_w, k=n_c)
    ranges = [(bisect_left(ep_pub, s), bisect_left(ep_pub, e)) for _, s, e in camps]
    randrange = rng.randrange
    c_brand = [camps[c][0] for c in camp_pick]
    c_ep = [randrange(*ranges[c]) for c in camp_pick]
    types = ["host_read", "pre_roll", "mid_roll", "post_roll", "organic"]
    t_base = rng.choices(types, weights=[20, 10, 15, 5, 50], k=n_b)
    t_camp = rng.choices(types, weights=[35, 15, 30, 10, 10], k=n_c)
    brand_ids = b_brand + c_brand
    eidx = b_ep + c_ep
    mtypes = t_base + t_camp
    m_lines = []
    ver = rng.choices(["v1.9", "v2.0"], weights=[3, 7], k=n_mentions)
    for k in range(n_mentions):
        i = eidx[k]
        off_s = randrange(ep_dur[i])
        seg = off_s * SEGMENTS_PER_EPISODE // ep_dur[i]
        conf = 0.4 + 0.6 * rand() ** 0.7
        m_lines.append(f"{ep_pub[i] + off_s}\t{brand_ids[k]}\t{ep_pod[i]}\t{i + 1}\t{seg}\t"
                       f"{off_s * 1000 + randrange(1000)}\t{mtypes[k]}\t{conf:.3f}\t{ver[k]}")
    rng.shuffle(m_lines)  # arrival order should not be sorted by time
    flush("podcast.brand_mentions",
          "mentioned_at,brand_id,podcast_id,episode_id,segment_idx,offset_ms,mention_type,confidence,detector_version",
          m_lines, "brand_mentions", stats)
    del m_lines

    # --- downloads --------------------------------------------------------
    base = int(n_downloads / (1 + SAME_DAY_REPEAT))
    d_ep = rng.choices(range(N_EPISODES), cum_weights=ep_cum, k=base)
    n_listeners = int(600_000 * max(a.scale, 0.05))
    mask = (1 << 64) - 1
    d_lis = [(int(rand() * n_listeners) * 0x9E3779B97F4A7C15 + 12345) & mask for _ in range(base)]
    d_reg = rng.choices(REGIONS, weights=zipf(len(REGIONS), 1.1), k=base)
    d_dev = rng.choices(DEVICES, weights=DEVICE_W, k=base)
    getbits = rng.getrandbits

    def uuid():
        h = "%032x" % getbits(128)
        return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"

    d_ts = []
    for i in d_ep:
        pub = ep_pub[i]
        delay = int(rng.expovariate(1 / (3 * 86400)))
        ts = pub + delay
        if ts >= end_ts:
            ts = pub + delay % (end_ts - pub)
        d_ts.append(ts)
    rows = [(d_ts[k], d_ep[k], d_lis[k], d_reg[k], d_dev[k]) for k in range(base)]
    for k in rng.sample(range(base), int(base * SAME_DAY_REPEAT)):
        ts, e, lis, reg, dev = rows[k]
        ts2 = ts - ts % 86400 + (ts % 86400 + randrange(60, 7200)) % 86400
        rows.append((ts2 if ts2 < end_ts else ts, e, lis, reg, dev))
    rng.shuffle(rows)
    d_lines = [f"{ts}\t{uuid()}\t{ep_pod[e]}\t{e + 1}\t{reg}\t{dev}\t{lis}\t{randrange(300_000, 60_000_000)}"
               for ts, e, lis, reg, dev in rows]
    dl_cols = "downloaded_at,download_id,podcast_id,episode_id,region,device,listener_hash,bytes"
    flush("podcast.downloads", dl_cols, d_lines, "downloads (unique ids)", stats)
    # At-least-once delivery: ~1% of rows arrive a second time in later inserts.
    # ingested_at defaults to now(), so the redelivered copy is the newer version.
    redo = [d_lines[k] for k in rng.sample(range(len(d_lines)), int(len(d_lines) * REDELIVER))]
    flush("podcast.downloads", dl_cols, redo, "downloads (redelivered)", stats)
    del d_lines, rows

    # --- transcript segments ---------------------------------------------
    n_seg_eps = int(N_EPISODES * min(1.0, SEGMENT_SAMPLE * a.scale))
    sample = rng.sample(range(N_EPISODES), n_seg_eps)
    sentences = [" ".join(rng.choices(WORDS, k=rng.randint(6, 14))) + "." for _ in range(4000)]
    seg_brand = rng.choices(brand_names, cum_weights=brand_cum, k=n_seg_eps * SEGMENTS_PER_EPISODE)
    s_lines = []
    n = 0
    for i in sample:
        dur_ms = ep_dur[i] * 1000
        for s in range(SEGMENTS_PER_EPISODE):
            text = sentences[randrange(4000)]
            if rand() < 0.08:
                text += f" This part was brought to you by {seg_brand[n]}."
            n += 1
            s_lines.append(f"{ep_pod[i]}\t{i + 1}\t{s}\t{dur_ms * s // SEGMENTS_PER_EPISODE}\t"
                           f"{dur_ms * (s + 1) // SEGMENTS_PER_EPISODE}\t{ep_pub[i]}\t{text}")
    flush("podcast.transcript_segments",
          "podcast_id,episode_id,segment_idx,start_ms,end_ms,published_at,text",
          s_lines, "transcript_segments", stats)

    print(f"done in {time.time() - t_start:.1f}s total")
    print("table row counts:")
    for t in ["podcasts", "episodes", "brands", "campaigns", "brand_mentions", "downloads",
              "transcript_segments", "brand_mentions_daily", "downloads_daily"]:
        print(f"  {t:22s} {int(ch.rows(f'SELECT count() FROM podcast.{t}')[0][0]):>10,}")


if __name__ == "__main__":
    main()
