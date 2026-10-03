"""
Builds staff-only sample editions of the Daily Briefing for counsel (counsel's
review of the 3 Oct samples: "send counsel 5 fresh sample editions").

Sample editions are stored in briefing_editions with is_sample = true. Readers
never see them, even after the Briefing is public. Editors review, rewrite,
leave out and approve them at /admin/briefing like a real edition, and every
action is written to the change log.

  railway run python scripts/build_sample_editions.py                 # plan only
  railway run python scripts/build_sample_editions.py --regenerate --yes

--regenerate first re-runs the cleared summary (amended prompt) for every
selected story, so the samples show the amended rules. This is a paid model
call per story; the plan printed without --yes gives the count. The new
summary also becomes the story page's summary, as it would on any re-run.

Dates must be before today and must not already have an edition.
"""
import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.briefing_edition import build_edition, candidate_clusters, edition_window, lagos_today, select_clusters  # noqa: E402
from app.db import supabase  # noqa: E402
from app.summarizer import generate_cluster_summary  # noqa: E402

# 25 Sep: ADC campaign council (to be rewritten by an editor). 29 Sep: "Alleged
# forgery" (Atiku motion). 30 Sep: Manchester City. 1 Oct: Adeyemi arraignment.
# 3 Oct: the latest full day before the edition table existed.
DEFAULT_DATES = ["2026-09-25", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-03"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", default=",".join(DEFAULT_DATES))
    ap.add_argument("--regenerate", action="store_true", help="re-run the cleared summary for each selected story (paid)")
    ap.add_argument("--yes", action="store_true", help="carry out the plan")
    args = ap.parse_args()

    days = [date.fromisoformat(d.strip()) for d in args.dates.split(",") if d.strip()]
    plan = []
    for day in days:
        if day >= lagos_today():
            sys.exit(f"{day}: sample dates must be before today")
        if supabase.table("briefing_editions").select("id").eq("date", day.isoformat()).limit(1).execute().data:
            sys.exit(f"{day}: an edition already exists for this date")
        start, end = edition_window(day)
        selected = select_clusters(candidate_clusters(start, end))
        plan.append((day, selected))
        print(f"{day}: {len(selected)} stories selected")
        for c in selected:
            print(f"    {c['representative_title'][:100]}")

    calls = sum(len(s) for _, s in plan) if args.regenerate else 0
    print(f"\nPlan: {len(plan)} sample editions; {calls} paid summary calls.")
    if not args.yes:
        print("Nothing written. Re-run with --yes to carry out the plan.")
        return

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
