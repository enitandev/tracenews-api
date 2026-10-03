"""
Preserve and reconstruct what the old MonitoringSignals widget published,
1 Sep - 2 Oct 2026 (counsel's instruction, 2 Oct 2026).

Run from the repo root with the production Supabase env vars set, e.g.
    railway run python scripts/export_widget_record.py
It only reads. Output goes to widget_record_<UTC timestamp>/:

  raw/<table>.jsonl   full copies of every table the widget's inputs came from
  manifest.json       row counts and SHA-256 of every raw file
  instances.csv       every story where the widget's own rules fired, replayed
                      over the stored coverage snapshots and score history
  instances_named.csv the subset with a named politician or party, ranked
                      for counsel's "worst instances" review

What the widget showed (src/components/MonitoringSignals.jsx, removed 2 Oct):
  One-Sided Coverage  total >= 5 distinct outlets, and either
                      watchdog >= 60% and govt <= 10%  -> "Mostly reported by
                      accountability outlets — government-aligned outlets have
                      not covered this."
                      govt >= 70% and watchdog <= 10%  -> "Mostly reported by
                      government-aligned outlets — accountability outlets have
                      not covered this."
                      Tap-to-explain added "...may indicate selective
                      suppression." / "...may indicate coordinated
                      amplification."
                      Shown on the story page and homepage lead (and, 1-5 Sep,
                      as a pill on every homepage list item).
  Copy-and-Paste      story page only; >= 4 distinct outlets with an S2 score
                      and >= 60% of them below 40 -> "{x} of {y} outlets
                      published nearly the same report — {z} did their own
                      reporting." (z = outlets with S2 >= 70). Names no outlet.

Replay limits, stated in the output:
  - The widget ran on the live distribution at page load; the replay uses the
    coverage_snapshots rows (written hourly or when outlet count changes), so
    a firing between two snapshots can be missed or its timing approximated.
  - Copy-and-Paste uses each outlet's S2 from tii_score_history as at the
    snapshot time; where no earlier history row exists, the current
    outlet_behavioral_scores value is used and the row is marked approximate.
  - Outlets counted for Copy-and-Paste are those with a story in the cluster
    fetched at or before the snapshot.
"""
import csv
import hashlib
import json
import os
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import supabase  # noqa: E402
from app.tier_utils import normalize_tier_distribution  # noqa: E402

WINDOW_START = "2026-09-01T00:00:00+00:00"
# Removal commit 1ca67af / 8b4d302 was deployed on 2 Oct; anything up to the
# end of 2 Oct is included so nothing at the edge is missed.
WINDOW_END = "2026-10-02T23:59:59+00:00"

# Small or offset-safe tables, copied whole. Columns are listed where the
# table carries embeddings; "*" elsewhere.
TABLES = {
    "clusters": "id, slug, representative_title, category, first_seen_at, outlet_count, created_at, coverage_stats, monitoring_flags",
    "stories": "id, cluster_id, outlet_id, outlet_slug, outlet_name, title, url, published_at, fetched_at, created_at",
    "outlets": "*",
    "outlet_behavioral_scores": "*",
    "tii_score_history": "*",
    "politicians": "*",
    "parties": "*",
}
# coverage_snapshots is too large for offset paging (deep offsets hit the
# statement timeout), so it is read per batch of clusters, within the window,
# through its cluster index. story_entities is read for the stories in the
# clusters where the widget fired.
BATCH = 100

WATCHDOG_LINE = "Mostly reported by accountability outlets — government-aligned outlets have not covered this."
GOVT_LINE = "Mostly reported by government-aligned outlets — accountability outlets have not covered this."


def execute(query):
    """One retry for a transient timeout; a second failure stops the export."""
    try:
        return query.execute().data or []
    except Exception as e:
        print(f"  retrying after: {e}")
        return query.execute().data or []


def fetch_all(table, columns):
    rows, offset = [], 0
    while True:
        page = execute(supabase.table(table).select(columns).range(offset, offset + 999))
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


def fetch_in_batches(table, key, ids, extra=lambda q: q, order=None):
    rows, ids = [], list(ids)
    for i in range(0, len(ids), BATCH):
        batch, offset = ids[i:i + BATCH], 0
        while True:
            q = extra(supabase.table(table).select("*").in_(key, batch))
            if order:
                q = q.order(key).order(order)
            page = execute(q.range(offset, offset + 999))
            rows.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
        if (i // BATCH) % 100 == 0:
            print(f"  {table}: {min(i + BATCH, len(ids))}/{len(ids)} ids, {len(rows)} rows")
    return rows


def ts(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")) if value else None


def write_table(out_dir, manifest, table, rows):
    path = os.path.join(out_dir, "raw", f"{table}.jsonl")
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r, default=str, ensure_ascii=False) + "\n")
    with open(path, "rb") as f:
        digest = hashlib.sha256(f.read()).hexdigest()
    manifest["tables"][table] = {"rows": len(rows), "sha256": digest}
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"exported {table}: {len(rows)} rows")


def export(out_dir):
    os.makedirs(os.path.join(out_dir, "raw"))
    data, manifest = {}, {"exported_at": datetime.now(timezone.utc).isoformat(), "tables": {}}
    for table, columns in TABLES.items():
        data[table] = fetch_all(table, columns)
        write_table(out_dir, manifest, table, data[table])
    window = lambda q: q.gte("snapshot_at", WINDOW_START).lte("snapshot_at", WINDOW_END)  # noqa: E731
    data["coverage_snapshots"] = fetch_in_batches(
        "coverage_snapshots", "cluster_id", [c["id"] for c in data["clusters"]], window, order="snapshot_at")
    write_table(out_dir, manifest, "coverage_snapshots", data["coverage_snapshots"])
    return data, manifest


def one_sided(dist):
    total = sum(dist.values())
    if total < 5:
        return None
    govt, watchdog = dist["govt_aligned"] / total * 100, dist["watchdog"] / total * 100
    if watchdog >= 60 and govt <= 10:
        return "one_sided_watchdog", WATCHDOG_LINE
    if govt >= 70 and watchdog <= 10:
        return "one_sided_govt", GOVT_LINE
    return None


def reconstruct(data, out_dir, load_entities):
    start, end = ts(WINDOW_START), ts(WINDOW_END)
    clusters = {c["id"]: c for c in data["clusters"]}
    outlets_by_id = {o["id"]: o for o in data["outlets"]}

    stories_by_cluster = defaultdict(list)
    for s in data["stories"]:
        if s.get("cluster_id"):
            stories_by_cluster[s["cluster_id"]].append(s)

    history = defaultdict(list)  # slug -> sorted [(scored_at, s2)]
    for h in data["tii_score_history"]:
        if h.get("s2_score") is not None and h.get("scored_at"):
            history[h["outlet_slug"]].append((ts(h["scored_at"]), h["s2_score"]))
    for v in history.values():
        v.sort(key=lambda x: x[0])
    current_s2 = {b["outlet_slug"]: b.get("s2_score") for b in data["outlet_behavioral_scores"]}

    def s2_at(slug, when):
        rows = history.get(slug)
        if rows:
            i = bisect_right([r[0] for r in rows], when)
            if i:
                return rows[i - 1][1], False
        return current_s2.get(slug), True

    instances = {}  # (cluster_id, signal) -> record
    unusable = 0
    for snap in data["coverage_snapshots"]:
        at = ts(snap.get("snapshot_at"))
        cid = snap.get("cluster_id")
        if not at or not (start <= at <= end) or cid not in clusters:
            continue
        dist = normalize_tier_distribution(snap.get("coverage_tier_distribution"))
        if dist is None:
            unusable += 1
            continue
        fired = []
        os_hit = one_sided(dist)
        if os_hit:
            fired.append((os_hit[0], os_hit[1], dist, None))
        if sum(dist.values()) >= 5:
            # Copy-and-Paste: distinct outlets present by this snapshot.
            slugs, approx = {}, False
            for s in stories_by_cluster[cid]:
                seen = ts(s.get("fetched_at") or s.get("created_at"))
                slug = s.get("outlet_slug") or (outlets_by_id.get(s.get("outlet_id")) or {}).get("slug")
                if not slug or slug in slugs or (seen and seen > at):
                    continue
                score, was_approx = s2_at(slug, at)
                if score is None:
                    continue
                slugs[slug] = score
                approx = approx or was_approx
            n = len(slugs)
            if n >= 4:
                rep = sum(1 for v in slugs.values() if v < 40)
                orig = sum(1 for v in slugs.values() if v >= 70)
                if rep / n * 100 >= 60:
                    line = f"{rep} of {n} outlets published nearly the same report — {orig} did their own reporting."
                    fired.append(("copy_paste", line, dist, {"approx_scores": approx,
                                  "republishers": sorted(k for k, v in slugs.items() if v < 40)}))
        for signal, line, d, extra in fired:
            rec = instances.setdefault((cid, signal), {"first": at, "last": at, "checks": 0, "lines": set(),
                                                       "peak": d, "extra": extra})
            if at >= rec["last"]:
                rec["peak"] = d
            rec["first"], rec["last"] = min(rec["first"], at), max(rec["last"], at)
            rec["checks"] += 1
            rec["lines"].add(line)
            if extra:
                rec["extra"] = extra

    # Named politicians and parties, for the stories in clusters that fired.
    fired_story_ids = {st["id"] for cid, _ in instances for st in stories_by_cluster[cid]}
    politicians = {p["id"]: p.get("common_name") for p in data["politicians"]}
    parties = {p["id"]: p.get("abbreviation") for p in data["parties"]}
    subjects_by_story = defaultdict(set)
    for e in load_entities(sorted(fired_story_ids)):
        if e.get("politician_id") in politicians:
            subjects_by_story[e["story_id"]].add(politicians[e["politician_id"]])
        if e.get("party_id") in parties:
            subjects_by_story[e["story_id"]].add(parties[e["party_id"]])

    fields = ["cluster_id", "slug", "story_url", "title", "category", "signal", "strings_served",
              "surfaces", "first_fired_at", "last_fired_at", "checks_fired", "tier_counts_at_last_check",
              "named_subjects", "copy_paste_republisher_outlets", "scores_approximate"]
    rows = []
    for (cid, signal), rec in instances.items():
        c = clusters[cid]
        subjects = set()
        for s in stories_by_cluster[cid]:
            subjects |= subjects_by_story.get(s["id"], set())
        extra = rec["extra"] or {}
        rows.append({
            "cluster_id": cid,
            "slug": c.get("slug"),
            "story_url": f"https://tracenews.ng/story/{c['slug']}" if c.get("slug") else "",
            "title": c.get("representative_title"),
            "category": c.get("category"),
            "signal": signal,
            "strings_served": " | ".join(sorted(rec["lines"])),
            "surfaces": "story page" if signal == "copy_paste" else "story page; homepage lead if it led; list pill 1-5 Sep",
            "first_fired_at": rec["first"].isoformat(),
            "last_fired_at": rec["last"].isoformat(),
            "checks_fired": rec["checks"],
            "tier_counts_at_last_check": json.dumps(rec["peak"]),
            "named_subjects": "; ".join(sorted(subjects)),
            "copy_paste_republisher_outlets": "; ".join(extra.get("republishers", [])),
            "scores_approximate": extra.get("approx_scores", ""),
        })
    rows.sort(key=lambda r: (not r["named_subjects"], r["category"] or "", r["first_fired_at"]))

    for name, subset in (("instances.csv", rows), ("instances_named.csv", [r for r in rows if r["named_subjects"]])):
        with open(os.path.join(out_dir, name), "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(subset)
    print(f"instances: {len(rows)} ({sum(1 for r in rows if r['named_subjects'])} with named subjects); "
          f"{unusable} snapshots unusable and skipped")


NOTES = """How instances.csv was built

Each row is a story where the retired MonitoringSignals widget's own rules
were met at one or more stored coverage snapshots between 1 Sep and 2 Oct
2026. The snapshots are written hourly or when a story's outlet count
changes, so a firing between two snapshots can be missed or its timing
approximated.

One-Sided Coverage is replayed from the tier counts stored in each snapshot.

Copy-and-Paste depends on each outlet's S2 score at the time. The score
history table (tii_score_history) held {history_rows} row(s) at export, so
the scores in force during September were not recorded; the replay uses
each outlet's current S2 score (column scores_approximate = True). Rows for
Copy-and-Paste show where it would fire on today's scores, not a verified
record of what was served.

"homepage lead if it led": the export cannot tell which story led the
homepage at a given moment.
"""


def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = f"widget_record_{stamp}"
    os.makedirs(out_dir)
    data, manifest = export(out_dir)

    def load_entities(story_ids):
        rows = fetch_in_batches("story_entities", "story_id", story_ids)
        write_table(out_dir, manifest, "story_entities", rows)
        return rows

    reconstruct(data, out_dir, load_entities)
    with open(os.path.join(out_dir, "NOTES.txt"), "w") as f:
        f.write(NOTES.format(history_rows=len(data["tii_score_history"])))
    print(f"done: {out_dir}/")


if __name__ == "__main__":
    main()
