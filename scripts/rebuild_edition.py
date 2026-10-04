"""
Rebuild one real Daily Briefing edition with the current code. Use it when
the rules change after the morning build (e.g. the launch fixes of 4 Oct
2026 merged after that day's edition was built).

  railway run python scripts/rebuild_edition.py              # today: shows the plan only
  railway run python scripts/rebuild_edition.py --yes        # carry it out
  railway run python scripts/rebuild_edition.py --date 2026-10-04 --yes

The old items, their approvals and change-log entries are first saved to
replaced_edition_<date>_<stamp>.json in the current folder, then removed;
the edition is built again (one paid model call per story, for the fuller
sections). Held items need an editor's approval again. Only today's edition
or a later one can be rebuilt: an edition readers may already have seen is
never replaced.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.briefing_edition import build_edition, candidate_clusters, edition_window, lagos_today, select_clusters  # noqa: E402
from app.db import supabase  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", help="YYYY-MM-DD (default: today in Lagos)")
    ap.add_argument("--yes", action="store_true", help="carry out the plan")
    args = ap.parse_args()
    day = date.fromisoformat(args.date) if args.date else lagos_today()
    if day < lagos_today():
        sys.exit(f"{day}: only today's edition or a later one can be rebuilt")

    existing = supabase.table("briefing_editions").select("*").eq("date", day.isoformat()).execute().data or []
    if any(r.get("is_sample") for r in existing):
        sys.exit(f"{day}: this date holds sample items; use scripts/build_sample_editions.py")
    approved = [r for r in existing if r.get("approved_by")]
    start, end = edition_window(day)
    selected = select_clusters(candidate_clusters(start, end))
    print(f"{day}: {len(existing)} items now ({len(approved)} approved); {len(selected)} stories selected for the rebuild")
    for c in selected:
        print(f"    {c['representative_title'][:100]}")
    print(f"\nPlan: replace {len(existing)} items; up to {len(selected)} paid model calls (fuller sections).")
    if approved:
        print(f"{len(approved)} approvals will need to be given again.")
    if not args.yes:
        print("Nothing written. Re-run with --yes to carry out the plan.")
        return

    if existing:
        ids = [r["id"] for r in existing]
        log = supabase.table("briefing_edit_log").select("*").in_("edition_id", ids).execute().data or []
        backup = f"replaced_edition_{day}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        with open(backup, "w") as f:
            json.dump({"editions": existing, "change_log": log}, f, indent=2, default=str, ensure_ascii=False)
        print(f"Backed up {len(existing)} items and {len(log)} change-log entries to {backup}")
        if log:
            supabase.table("briefing_edit_log").delete().in_("edition_id", ids).execute()
        supabase.table("briefing_editions").delete().in_("id", ids).eq("is_sample", False).execute()
    print(f"{day}: {build_edition(day)}")
    print("\nNext: approve the held items at /admin/briefing.")


if __name__ == "__main__":
    main()
