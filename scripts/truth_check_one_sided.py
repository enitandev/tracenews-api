"""
Truth check of the old widget's One-Sided Coverage firings (counsel's scoping
note of 3 Oct 2026, section 2).

Offline: reads the folder written by export_widget_record.py, touches no
database. Run from the repo root:
    python scripts/truth_check_one_sided.py widget_record_<stamp>
Writes <folder>/truth_check_one_sided.csv.

For each firing, "the missing tier" is the tier the widget said had not
covered the story (government-aligned for the watchdog variant; watchdog for
the government variant). Two checks:

  A. Same story, ingested late. An article from a missing-tier outlet that is
     in the story's cluster, published at or before the last firing, but
     fetched after the first firing. The tier had covered the story while the
     widget said it had not: the statement was false for that period.

  B. Same story, clustered apart. A missing-tier article published in the
     display window (or the 48 hours before it) in a different cluster whose
     headline shares most of its key words with a headline in this cluster.
     These are candidates only; each needs a human read.

Result per firing:
  FALSE (ingestion lag)       check A found an article
  REVIEW (possible miss)      check B found a candidate; a human decides
  NO EVIDENCE OF COVERAGE     neither check found anything

Limits: an article TraceNews never ingested cannot be detected here. Tiers are
today's outlet tiers; an outlet whose alignment changed since September would
be classified on its current value.
"""
import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tier_utils import get_outlet_tier  # noqa: E402

LOOKBACK = timedelta(hours=48)
MIN_SHARED_WORDS = 3
MIN_OVERLAP = 0.5
STOPWORDS = set("""a an and are as at be by for from has have he her his in is it its of on or
over says said she that the their they this to was were will with after before
new over under into out up about against amid as why how what who more than
""".split())

MISSING_TIER = {"one_sided_watchdog": "govt_aligned", "one_sided_govt": "watchdog"}


def ts(value):
    if not value:
        return None
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.now().astimezone().tzinfo)


def words(title):
    return {w for w in re.findall(r"[a-z0-9₦$]+", (title or "").lower()) if w not in STOPWORDS and len(w) > 2}


def read_jsonl(folder, table):
    with open(os.path.join(folder, "raw", f"{table}.jsonl")) as f:
        return [json.loads(line) for line in f]


def main():
    folder = sys.argv[1]
    outlets = {o["id"]: o for o in read_jsonl(folder, "outlets")}
    tier_of = {oid: get_outlet_tier(o.get("government_alignment"), o.get("is_blog")) for oid, o in outlets.items()}

    stories = read_jsonl(folder, "stories")
    by_cluster = defaultdict(list)
    by_tier = defaultdict(list)
    for s in stories:
        s["_pub"], s["_seen"] = ts(s.get("published_at")), ts(s.get("fetched_at") or s.get("created_at"))
        s["_tier"] = tier_of.get(s.get("outlet_id"), "unscored")
        if s.get("cluster_id"):
            by_cluster[s["cluster_id"]].append(s)
        by_tier[s["_tier"]].append(s)

    with open(os.path.join(folder, "instances.csv")) as f:
        firings = [r for r in csv.DictReader(f) if r["signal"] in MISSING_TIER]

    out_rows = []
    for r in firings:
        cid, missing = r["cluster_id"], MISSING_TIER[r["signal"]]
        first, last = ts(r["first_fired_at"]), ts(r["last_fired_at"])
        cluster = by_cluster.get(cid, [])

        late = [s for s in cluster if s["_tier"] == missing and s["_pub"] and s["_pub"] <= last
                and s["_seen"] and s["_seen"] > first]

        cluster_words = [words(s.get("title")) for s in cluster] + [words(r["title"])]
        candidates = []
        for s in by_tier[missing]:
            if s.get("cluster_id") == cid or not s["_pub"] or not (first - LOOKBACK <= s["_pub"] <= last):
                continue
            w = words(s.get("title"))
            best = max((len(w & cw), len(w & cw) / max(1, min(len(w), len(cw)))) for cw in cluster_words)
            if best[0] >= MIN_SHARED_WORDS and best[1] >= MIN_OVERLAP:
                candidates.append((best[1], s))
        candidates.sort(key=lambda x: -x[0])

        if late:
            result = "FALSE (ingestion lag)"
        elif candidates:
            result = "REVIEW (possible miss)"
        else:
            result = "NO EVIDENCE OF COVERAGE"

        def describe(s):
            o = outlets.get(s.get("outlet_id"), {})
            return f"{o.get('name') or s.get('outlet_name')} | published {s.get('published_at')} | fetched {s.get('fetched_at')} | {s.get('title')} | {s.get('url')}"

        out_rows.append({
            "result": result,
            "title": r["title"],
            "story_url": r["story_url"],
            "signal": r["signal"],
            "string_served": r["strings_served"],
            "missing_tier": missing,
            "first_fired_at": r["first_fired_at"],
            "last_fired_at": r["last_fired_at"],
            "checks_fired": r["checks_fired"],
            "named_subjects": r["named_subjects"],
            "late_ingested_articles": " || ".join(describe(s) for s in late),
            "candidate_articles_other_clusters": " || ".join(describe(s) for _, s in candidates[:5]),
        })

    order = {"FALSE (ingestion lag)": 0, "REVIEW (possible miss)": 1, "NO EVIDENCE OF COVERAGE": 2}
    out_rows.sort(key=lambda x: (order[x["result"]], x["first_fired_at"]))
    path = os.path.join(folder, "truth_check_one_sided.csv")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()) if out_rows else ["result"])
        w.writeheader()
        w.writerows(out_rows)
    counts = defaultdict(int)
    for x in out_rows:
        counts[x["result"]] += 1
    print(f"{len(out_rows)} one-sided firings checked: " + "; ".join(f"{k}: {v}" for k, v in sorted(counts.items())))
    print(f"written: {path}")


if __name__ == "__main__":
    main()
