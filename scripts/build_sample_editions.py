"""
Builds staff-only sample editions of the Daily Briefing for counsel (counsel's
review of the 3 Oct samples: "send counsel 5 fresh sample editions").

Sample editions are stored in briefing_editions with is_sample = true. Readers
never see them, even after the Briefing is public. Editors review, rewrite,
leave out and approve them at /admin/briefing like a real edition, and every
action is written to the change log.

  railway run python scripts/build_sample_editions.py                 # plan only
  railway run python scripts/build_sample_editions.py --regenerate --yes
  railway run python scripts/build_sample_editions.py --replace --regenerate --yes

--replace rebuilds dates that already have a SAMPLE edition (never a real
one). It first writes the old sample rows and their change-log entries to
replaced_samples_<stamp>.json in the current folder, then removes them.

Every built item also gets the fuller sections (Who said what, What happens
next, Background): one more paid model call per story.

--regenerate first re-runs the cleared summary (amended prompt) for every
selected story, so the samples show the amended rules. This is a paid model
call per story; the plan printed without --yes gives the count. The new
summary also becomes the story page's summary, as it would on any re-run.

Dates must be before today and must never have a real edition.
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.briefing_edition import build_edition, candidate_clusters, edition_window, lagos_today, select_clusters  # noqa: E402
from app.db import supabase  # noqa: E402
from app.summarizer import generate_cluster_summary  # noqa: E402

# 25 Sep: ADC campaign council (to be rewritten by an editor). 29 Sep: "Alleged
# forgery" (Atiku motion). 30 Sep: Manchester City. 1 Oct: Adeyemi arraignment.
# 2 Oct: the latest full day of the first sample set.
DEFAULT_DATES = ["2026-09-25", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", default=",".join(DEFAULT_DATES))
    ap.add_argument("--regenerate", action="store_true", help="re-run the cleared summary for each selected story (paid)")
    ap.add_argument("--replace", action="store_true", help="rebuild dates that already have a sample edition (backs them up first)")
    ap.add_argument("--yes", action="store_true", help="carry out the plan")
    args = ap.parse_args()

    days = [date.fromisoformat(d.strip()) for d in args.dates.split(",") if d.strip()]
    plan, to_replace = [], []
    for day in days:
        if day >= lagos_today():
            sys.exit(f"{day}: sample dates must be before today")
        existing = supabase.table("briefing_editions").select("*").eq("date", day.isoformat()).execute().data or []
        if existing:
            if any(not r.get("is_sample") for r in existing):
                sys.exit(f"{day}: a real edition exists for this date; it is never replaced")
            if not args.replace:
                sys.exit(f"{day}: a sample edition already exists; add --replace to rebuild it")
            to_replace += existing
        start, end = edition_window(day)
        selected = select_clusters(candidate_clusters(start, end))
        plan.append((day, selected))
        print(f"{day}: {len(selected)} stories selected")
        for c in selected:
            print(f"    {c['representative_title'][:100]}")

    stories = sum(len(s) for _, s in plan)
    calls = stories * (2 if args.regenerate else 1)
    print(f"\nPlan: {len(plan)} sample editions; {calls} paid model calls "
          f"({'summary + sections' if args.regenerate else 'sections'} per story); "
          f"{len(to_replace)} old sample items to replace.")
    if not args.yes:
        print("Nothing written. Re-run with --yes to carry out the plan.")
        return

    if to_replace:
        ids = [r["id"] for r in to_replace]
        log = supabase.table("briefing_edit_log").select("*").in_("edition_id", ids).execute().data or []
        backup = f"replaced_samples_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        with open(backup, "w") as f:
            json.dump({"editions": to_replace, "change_log": log}, f, indent=2, default=str, ensure_ascii=False)
        print(f"Backed up {len(to_replace)} old sample items and {len(log)} change-log entries to {backup}")
        if log:
            supabase.table("briefing_edit_log").delete().in_("edition_id", ids).execute()
        supabase.table("briefing_editions").delete().in_("id", ids).eq("is_sample", True).execute()

    failed = []
    for day, selected in plan:
        if args.regenerate:
            for c in selected:
                if generate_cluster_summary(c["id"]) is None:
                    failed.append(c["representative_title"])
        print(f"{day}: {build_edition(day, sample=True)}")
    if failed:
        print(f"\nSummary re-run failed for {len(failed)} stories (they are left out of the samples):")
        for t in failed:
            print(f"    {t}")
    print("\nNext: review the sample editions at /admin/briefing (pick each date), then run scripts/briefing_samples.py.")


if __name__ == "__main__":
    main()
