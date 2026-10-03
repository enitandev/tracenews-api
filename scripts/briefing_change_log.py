"""
Exports the Daily Briefing editor change log for counsel (counsel's review of
the 3 Oct samples, item 2: "At day 30 send counsel the change log").
Read-only.

  railway run python scripts/briefing_change_log.py --since 2026-10-10 [--until 2026-11-09] [--include-samples]

Writes briefing_change_log_<stamp>.csv: one row per editor action (rewrite,
leave out, restore, approve) with the editor's name, the time, and the text
before and after.
"""
import argparse
import csv
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import supabase  # noqa: E402

FIELDS = ["created_at", "date", "edition_id", "cluster_id", "is_sample", "editor", "action", "before", "after", "note"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", required=True, help="YYYY-MM-DD (UTC)")
    ap.add_argument("--until", help="YYYY-MM-DD (UTC), exclusive")
    ap.add_argument("--include-samples", action="store_true")
    args = ap.parse_args()

    q = supabase.table("briefing_edit_log").select("*").gte("created_at", args.since)
    if args.until:
        q = q.lt("created_at", args.until)
    if not args.include_samples:
        q = q.eq("is_sample", False)
    rows = q.order("created_at").execute().data or []

    out = f"briefing_change_log_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.csv"
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            w.writerow({k: json.dumps(r.get(k), ensure_ascii=False) if k in ("before", "after") else r.get(k) for k in FIELDS})
    print(f"{len(rows)} entries: " + ", ".join(f"{a} {sum(1 for r in rows if r['action'] == a)}"
                                                for a in ("rewrite", "leave_out", "restore", "approve")))
    print(f"done: {out}")


if __name__ == "__main__":
    main()
