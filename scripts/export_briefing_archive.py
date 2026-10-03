"""
Archive every Daily Briefing ever generated (counsel's consolidated
instruction, 3 Oct 2026, A1 and G). Read-only. Run from the repo root:
    railway run python scripts/export_briefing_archive.py
Writes briefing_archive_<UTC stamp>/:
  daily_briefings.jsonl  every row, all columns, as stored
  briefings_index.csv    one line per briefing: date, position, status,
                         story title and link, people and parties named
  manifest.json          row counts, SHA-256 of each file, and a fingerprint
                         of the generator code (app/daily_briefing.py),
                         which holds the prompts
"""
import csv
import hashlib
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from app.db import supabase  # noqa: E402

BATCH = 100


def fetch_all(table, columns="*"):
    rows, offset = [], 0
    while True:
        page = supabase.table(table).select(columns).range(offset, offset + 999).execute().data or []
        rows.extend(page)
        if len(page) < 1000:
            return rows
        offset += 1000


def fetch_in(table, key, ids, columns="*"):
    rows, ids = [], list(ids)
    for i in range(0, len(ids), BATCH):
        offset = 0
        while True:
            page = (supabase.table(table).select(columns).in_(key, ids[i:i + BATCH])
                    .range(offset, offset + 999).execute().data or [])
            rows.extend(page)
            if len(page) < 1000:
                break
            offset += 1000
    return rows


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    out = f"briefing_archive_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    os.makedirs(out)
    briefings = fetch_all("daily_briefings")
    raw = os.path.join(out, "daily_briefings.jsonl")
    with open(raw, "w") as f:
        for r in briefings:
            f.write(json.dumps(r, default=str, ensure_ascii=False) + "\n")

    cluster_ids = sorted({b["cluster_id"] for b in briefings if b.get("cluster_id")})
    clusters = {c["id"]: c for c in fetch_in("clusters", "id", cluster_ids, "id, slug, representative_title")}
    stories = fetch_in("stories", "cluster_id", cluster_ids, "id, cluster_id")
    story_cluster = {s["id"]: s["cluster_id"] for s in stories}
    entities = fetch_in("story_entities", "story_id", list(story_cluster))
    politicians = {p["id"]: p.get("common_name") for p in fetch_all("politicians", "id, common_name")}
    parties = {p["id"]: p.get("abbreviation") for p in fetch_all("parties", "id, abbreviation")}
    named = defaultdict(set)
    for e in entities:
        cid = story_cluster.get(e.get("story_id"))
        if e.get("politician_id") in politicians:
            named[cid].add(politicians[e["politician_id"]])
        if e.get("party_id") in parties:
            named[cid].add(parties[e["party_id"]])

    index = os.path.join(out, "briefings_index.csv")
    with open(index, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["date", "position", "generation_status", "title", "story_url", "named_people_and_parties", "briefing_id"])
        for b in sorted(briefings, key=lambda r: (str(r.get("date")), r.get("position") or 0)):
            c = clusters.get(b.get("cluster_id"), {})
            w.writerow([b.get("date"), b.get("position"), b.get("generation_status"),
                        c.get("representative_title", ""),
                        f"https://tracenews.ng/daily-briefing/{c['slug']}" if c.get("slug") else "",
                        "; ".join(sorted(n for n in named.get(b.get("cluster_id"), set()) if n)), b.get("id")])

    generator = os.path.join(ROOT, "app", "daily_briefing.py")
    manifest = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "briefings": len(briefings),
        "dates": sorted({str(b.get("date")) for b in briefings}),
        "with_named_people_or_parties": sum(1 for b in briefings if named.get(b.get("cluster_id"))),
        "files": {os.path.basename(p): sha(p) for p in (raw, index)},
        "generator_code_sha256": sha(generator),
    }
    with open(os.path.join(out, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)
    print(f"{len(briefings)} briefings across {len(manifest['dates'])} days; "
          f"{manifest['with_named_people_or_parties']} name a politician or party")
    print(f"done: {out}/")


if __name__ == "__main__":
    main()
