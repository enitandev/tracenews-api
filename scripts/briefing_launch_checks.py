"""
Counsel's launch tests (4 Oct 2026, fixes 1-5) on the live sample editions.
Read-only: no database writes, no model calls.

  railway run python scripts/briefing_launch_checks.py

For every sample item it re-applies the build-time corrections and the
read-time routing with the current code, using the stored summary and
sections, every outlet's headline for the story, the source text and the
outlet list, exactly as the next build would. It then reports PASS or FAIL
for each item counsel named, and the counts for all sample items.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import briefing_edition as be  # noqa: E402
from app.briefing_extras import section_texts  # noqa: E402
from app.db import supabase  # noqa: E402
from app.summarizer import cluster_articles_text  # noqa: E402


def rerun(row, cluster, registry, outlets):
    summary = be.latest_summary(cluster["id"])
    headlines = [cluster.get("representative_title")] + [
        a.get("title") for a in be.source_articles(cluster["id"]) if a.get("title") != cluster.get("representative_title")]
    src = cluster_articles_text(cluster["id"])
    title, bullets, extras, notes, out = be.auto_correct(
        headlines, (summary or {}).get("bullets") or [], row.get("extras"), src, registry, outlets)
    be.assert_no_source_numbers(title, bullets, extras)
    if out:
        return {"title": None, "bullets": bullets, "extras": extras, "notes": notes, "lane": "left_out", "reasons": [out]}
    a = be.assess_item(title, bullets, src, registry, section_texts(extras))
    return {"title": a["title"], "bullets": bullets, "extras": extras, "notes": notes, "lane": a["lane"], "reasons": a["reasons"]}


def reader_text(r):
    ex = r["extras"] or {}
    return " ".join([r["title"] or ""] + list(r["bullets"]) + list(ex.get("next") or []) + list(ex.get("background") or [])
                    + [q.get("quote", "") for q in ex.get("quotes") or []])


CHECKS = [
    # (fix, item, headline fragment, test, description)
    ("1", "Adamawa troops", "Troops kill scores of terrorists",
     lambda r: r["lane"] == "left_out" or (r["title"] and not be.headline_issues(r["title"], " ".join(r["bullets"]))
                                            and not re.search(r"\b(neutrali[sz]es?|success(es)?)\b", r["title"], re.I)),
     "no flat, unattributed killing or 'success' in the headline (item left out if none passes)"),
    ("1", "NDLEA", "NDLEA busts Nigerian-Mexican meth cartel",
     lambda r: r["lane"] == "left_out" or not re.search(r"\bkingpins?\b", r["title"] or "", re.I)
     or re.search(r"\b(suspected|alleged)\b", r["title"] or "", re.I),
     "no unqualified offender label in the headline"),
    ("2", "House of Reps budget", "House Of Reps Extends",
     lambda r: "civil society" not in reader_text(r) and "lawyers" not in reader_text(r),
     "the 'lawyers and civil society' concerns line is removed"),
    ("2", "Nigeria Dodged A Bullet @ 66", "Nigeria Dodged A Bullet",
     lambda r: not re.search(r"commentators|some voices|colonised|mixed feelings", reader_text(r), re.I),
     "collective-origin criticism removed from every section"),
    ("3", "Customs fire", "Fire guts Customs",
     lambda r: "electrical surge" not in reader_text(r).lower(),
     "no flat 'electrical surge' cause in any section"),
    ("4", "Adamawa troops", "Troops kill scores of terrorists",
     lambda r: "News Agency of Nigeria" not in reader_text(r),
     "no 'News Agency of Nigeria' in reader text"),
    ("4", "Nigeria Dodged A Bullet @ 66", "Nigeria Dodged A Bullet",
     lambda r: not re.search(r"\(Sources?\s*\d", reader_text(r)),
     "no '(Sources n)' in reader text"),
    ("5", "Dangote refinery", "Dangote to launch",
     lambda r: r["lane"] in ("review", "senior_review"),
     "goes to the editor lane (legal challenge)"),
    ("5", "US judge / White House ban", "US judge blocks White House ban",
     lambda r: not any("suspend" in x for x in r["reasons"]),
     "does not trigger on the suspension of the ban"),
]


def main():
    rows = supabase.table("briefing_editions").select("*").eq("is_sample", True).order("date").execute().data or []
    if not rows:
        sys.exit("No sample editions found.")
    clusters = {c["id"]: c for c in supabase.table("clusters").select("id, representative_title")
                .in_("id", [r["cluster_id"] for r in rows]).execute().data or []}
    registry, outlets = be.load_registry(), be.load_outlet_names()
    results = []
    for row in rows:
        cluster = clusters.get(row["cluster_id"])
        if cluster:
            results.append((row, cluster, rerun(row, cluster, registry, outlets)))

    failed = 0
    print("Counsel's launch tests, 4 Oct 2026\n")
    for fix, item, fragment, test, what in CHECKS:
        match = [(row, c, r) for row, c, r in results if fragment.lower() in (c.get("representative_title") or "").lower()]
        if not match:
            print(f"FAIL  fix {fix}  {item}: item not found in the sample editions")
            failed += 1
            continue
        row, c, r = match[0]
        ok = bool(test(r))
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  fix {fix}  {item}: {what}")
        print(f"      result: {r['lane']}; headline: {r['title'] or '(none)'}")
        for n in r["notes"]:
            print(f"      - {n[:140]}")
        for x in r["reasons"]:
            print(f"      routing: {x[:140]}")
    lanes = {}
    for _, _, r in results:
        lanes[r["lane"]] = lanes.get(r["lane"], 0) + 1
    print(f"\nAll {len(results)} sample items with the current code: "
          + ", ".join(f"{k} {v}" for k, v in sorted(lanes.items())))
    left = [(c.get("representative_title"), r["reasons"][0]) for _, c, r in results if r["lane"] == "left_out"]
    for t, why in left:
        print(f"  left out: {t} — {why}")
    print(f"\n{len(CHECKS) - failed} of {len(CHECKS)} tests pass." + ("" if not failed else " LAUNCH HOLDS."))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
