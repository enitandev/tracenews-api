"""
Sample editions of the rebuilt Daily Briefing for counsel (consolidated
instruction, 3 Oct 2026, B9). Read-only: no database writes, no model calls.

For each of the last DAYS days it selects stories exactly as the Briefing
does (stories first seen in the 24 hours before 06:00 Lagos, widest coverage
first), attaches each story's stored cleared summary, and applies the same
gate. Run from the repo root:
    railway run python scripts/briefing_samples.py
Writes briefing_samples_<stamp>/samples.html (what a reader would see, with
each item's gate status) and samples.json.
"""
import html
import json
import os
import sys
from datetime import datetime, time, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.briefing_edition import (  # noqa: E402
    LAGOS, coverage_counts, has_forbidden_token, latest_summary, select_clusters, summary_usable,
)
from app.briefingStrings import GATE_NEEDS_EDITOR_APPROVAL, MIN_DISTINCT_OUTLETS, UI  # noqa: E402
from app.db import supabase  # noqa: E402

DAYS = 14


def names_in(cluster_id):
    stories = supabase.table("stories").select("id").eq("cluster_id", cluster_id).execute().data or []
    ids = [s["id"] for s in stories][:100]
    if not ids:
        return []
    ents = supabase.table("story_entities").select("politician_id").in_("story_id", ids).eq("entity_type", "politician").execute().data or []
    pids = sorted({e["politician_id"] for e in ents if e.get("politician_id")})
    if not pids:
        return []
    rows = supabase.table("politicians").select("common_name").in_("id", pids).execute().data or []
    return sorted(r["common_name"] for r in rows if r.get("common_name"))


def edition_for(day):
    end = datetime.combine(day, time(6, 0), LAGOS)
    start = end - timedelta(hours=24)
    clusters = supabase.table("clusters").select(
        "id, slug, representative_title, category, first_seen_at, coverage_stats, stories(image_url)"
    ).gte("first_seen_at", start.isoformat()).lt("first_seen_at", end.isoformat()) \
        .gte("outlet_count", MIN_DISTINCT_OUTLETS).execute().data or []
    items, left_out = [], []
    for c in select_clusters(clusters):
        s = latest_summary(c["id"])
        if not summary_usable(s):
            left_out.append({"title": c["representative_title"], "why": "no usable summary (missing, flagged, suppressed or failed)"})
            continue
        token = has_forbidden_token(s.get("bullets") or [])
        if token:
            left_out.append({"title": c["representative_title"], "why": f"forbidden token: {token}"})
            continue
        status = ("Publishes automatically (gate: auto)" if s.get("gate") not in GATE_NEEDS_EDITOR_APPROVAL
                  else f"Held for a named editor's approval (gate: {s.get('gate')})")
        items.append({
            "title": c["representative_title"], "slug": c["slug"], "category": c.get("category"),
            "bullets": s.get("bullets") or [], "gate": s.get("gate"), "status": status,
            "coverage_counts": coverage_counts(c["id"]), "named_people": names_in(c["id"]),
        })
    return {"date": day.isoformat(), "items": items, "left_out": left_out}


def render(editions, counted_at):
    t = UI["tier_labels"]
    out = [f"<!doctype html><meta charset='utf-8'><title>{UI['title']} — sample editions</title>",
           "<style>body{font-family:sans-serif;max-width:820px;margin:auto;padding:24px;color:#222}"
           ".item{border:1px solid #ccc;border-radius:6px;padding:14px;margin:12px 0}.label{font-size:12px;color:#666}"
           ".status{font-size:12px;background:#f3f3f3;padding:4px 8px;display:inline-block;margin-bottom:8px}"
           ".counts{font-size:13px;color:#444}.out{font-size:12px;color:#888}</style>",
           f"<h1>{UI['title']} — sample editions</h1>",
           "<p>Built from stored cleared summaries with the Briefing's own selection and gate. Not published. "
           f"Coverage counts were taken when this file was generated ({counted_at}), not on the edition date.</p>"]
    for ed in editions:
        out.append(f"<h2>{ed['date']}</h2>")
        for it in ed["items"]:
            c = it["coverage_counts"]
            total = sum(c.values())
            out.append("<div class='item'>")
            out.append(f"<div class='status'>{html.escape(it['status'])}</div>")
            out.append(f"<h3>{html.escape(it['title'])}</h3><div class='label'>{UI['attribution_label']}</div><ul>")
            out += [f"<li>{html.escape(b)}</li>" for b in it["bullets"] if isinstance(b, str)]
            out.append("</ul>")
            out.append(f"<div class='counts'><b>{UI['coverage_heading']}:</b> {total} — "
                       f"{t['govt_aligned']} {c['govt_aligned']} · {t['mainstream']} {c['mainstream']} · {t['watchdog']} {c['watchdog']}</div>")
            out.append(f"<div class='label'>{UI['correction_link']} · {UI['methodology_link']}</div>")
            if it["named_people"]:
                out.append(f"<div class='out'>Named in the source articles: {html.escape(', '.join(it['named_people']))}</div>")
            out.append("</div>")
        for lo in ed["left_out"]:
            out.append(f"<div class='out'>Left out: {html.escape(lo['title'])} — {lo['why']}</div>")
    return "\n".join(out)


def main():
    today = datetime.now(LAGOS).date()
    editions = [edition_for(today - timedelta(days=n)) for n in range(DAYS)]
    editions = [e for e in editions if e["items"] or e["left_out"]]
    counted_at = datetime.now(timezone.utc).isoformat(timespec="minutes")
    out = f"briefing_samples_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    os.makedirs(out)
    with open(os.path.join(out, "samples.json"), "w") as f:
        json.dump(editions, f, indent=2, default=str, ensure_ascii=False)
    with open(os.path.join(out, "samples.html"), "w") as f:
        f.write(render(editions, counted_at))
    items = [i for e in editions for i in e["items"]]
    political_named = [i for i in items if i["category"] == "Politics" and i["named_people"]]
    print(f"{len(editions)} editions, {len(items)} items "
          f"({sum(1 for i in items if i['gate'] not in GATE_NEEDS_EDITOR_APPROVAL)} auto, "
          f"{sum(1 for i in items if i['gate'] in GATE_NEEDS_EDITOR_APPROVAL)} held for an editor); "
          f"{len(political_named)} political items naming individuals")
    print(f"done: {out}/samples.html")


if __name__ == "__main__":
    main()
