"""
Exports the Daily Briefing sample editions for counsel. Read-only: no
database writes, no model calls.

  railway run python scripts/briefing_samples.py
  railway run python scripts/briefing_samples.py --dates 2026-09-25,2026-09-30

Reads the editions built by scripts/build_sample_editions.py (or any real
edition) exactly as staff see them at /admin/briefing, and writes
briefing_samples_<stamp>/samples.html and samples.json. Each item shows:
  - what a reader would see (or that it is held / left out, and why);
  - the reviewer panel: routing reasons, editor rewrites, approval with the
    checklist, and "Named in the source articles" — reviewer-only, never
    shown to readers;
and the change log for those dates.
"""
import argparse
import html
import json
import os
import sys
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.briefing_edition import edition_items  # noqa: E402
from app.briefingStrings import EDITOR_CHECKLIST, UI  # noqa: E402
from app.db import supabase  # noqa: E402

LANE_TEXT = {
    "auto": "Publishes automatically",
    "review": "Held for a named editor (review)",
    "senior_review": "Held for a named editor (senior review: adverse context, principal office-holder)",
    "left_out": "Left out",
}


def e(s):
    return html.escape(str(s if s is not None else ""))


def counts_line(c):
    t = UI["tier_labels"]
    c = c or {}
    total = sum(c.get(k) or 0 for k in t)
    return f"<b>{e(UI['coverage_heading'])}:</b> {total} — " + " · ".join(f"{e(t[k])} {c.get(k) or 0}" for k in t)


def render(editions, log, generated):
    out = [f"<!doctype html><meta charset='utf-8'><title>{e(UI['title'])} — sample editions</title>",
           "<style>body{font-family:sans-serif;max-width:860px;margin:auto;padding:24px;color:#222}"
           ".item{border:1px solid #ccc;border-radius:6px;padding:14px;margin:14px 0}"
           ".reader{background:#fff}.label{font-size:12px;color:#666}.status{font-size:12px;font-weight:bold;margin-bottom:8px}"
           ".rev{margin-top:10px;padding:10px;background:#f6f3ea;border-left:3px solid #b08900;font-size:12px}"
           ".out{color:#999}.counts{font-size:13px;color:#444}table{border-collapse:collapse;font-size:12px}"
           "td,th{border:1px solid #ddd;padding:4px 6px;vertical-align:top}</style>",
           f"<h1>{e(UI['title'])} — sample editions</h1>",
           f"<p>Generated {e(generated)}. Built with the Briefing's own selection and routing, from the cleared "
           "summary prompt as amended in October 2026. Not published: sample editions are never shown to readers. "
           "The shaded panel under each item is the editor's view and never appears to readers.</p>"]
    for ed in editions:
        out.append(f"<h2>{e(ed['date'])}</h2>")
        shown = [i for i in ed["items"] if i["lane"] != "left_out"]
        out.append(f"<p class='label'>{len(ed['items'])} stories selected; "
                   f"{sum(1 for i in ed['items'] if i['publishable'])} would publish as the edition stands.</p>")
        for it in ed["items"]:
            status = LANE_TEXT[it["lane"]]
            if it["lane"] in ("review", "senior_review"):
                status += f" — approved by {it['approved_by']}" if it["approved_by"] else " — not yet approved"
            if it["lane"] == "senior_review" and it["approved_by"]:
                status += f" and {it['second_approved_by']}" if it["second_approved_by"] else " — second approver still needed"
            cls = "item" if it in shown else "item out"
            out.append(f"<div class='{cls}'><div class='status'>{e(status)}</div>")
            sec = UI["sections"]
            out.append(f"<h3>{e(it['title'])}</h3><div class='label'>{e(UI['attribution_label'])}</div>")
            out.append(f"<h4>{e(sec['what_happened'])}</h4><ul>")
            out += [f"<li>{e(b)}</li>" for b in it["bullets"] if isinstance(b, str)]
            out.append("</ul>")
            sections = it.get("sections") or {}
            for key in ("quotes", "next", "background"):
                rows = [q["line"] for q in sections.get("quotes") or []] if key == "quotes" else sections.get(key) or []
                if rows:
                    out.append(f"<h4>{e(sec[key])}</h4><ul>" + "".join(f"<li>{e(r)}</li>" for r in rows) + "</ul>")
            out.append(f"<div class='counts'>{counts_line(it['coverage_counts'])}</div>")
            out.append(f"<div class='label'>{e(UI['correction_link'])} · {e(UI['methodology_link'])}</div>")
            out.append("<div class='rev'><b>Editor's view (never shown to readers)</b><br>")
            out.append(f"Source headline: {e(it['source_headline'])}<br>")
            if it["reasons"]:
                out.append("Routing: " + "; ".join(e(r) for r in it["reasons"]) + "<br>")
            if it["edited_by"]:
                out.append(f"Rewritten by {e(it['edited_by'])} at {e(it['edited_at'])}. Model summary before the rewrite: "
                           + " / ".join(e(b) for b in it["summary_bullets"]) + "<br>")
            checks = (it.get("approval_checklist") or {}).get("party_checks") or []
            if checks:
                out.append("Party and candidacy descriptors checked: " + "; ".join(
                    f"{e(c['descriptor'])} (source: {e(c['source'])}, checked {e(c['checked_at'])})" for c in checks) + "<br>")
            if it.get("extras_dropped"):
                out.append("Removed by the section checks: " + "; ".join(e(d) for d in it["extras_dropped"]) + "<br>")
            if it.get("extras_error"):
                out.append(f"Fuller sections could not be generated: {e(it['extras_error'])}<br>")
            if it["named_in_sources"]:
                out.append(f"Named in the source articles: {e(', '.join(it['named_in_sources']))}<br>")
            out.append("</div></div>")
    out.append("<h2>Change log for these dates</h2>")
    if not log:
        out.append("<p>No editor actions.</p>")
    else:
        out.append("<table><tr><th>When (UTC)</th><th>Edition</th><th>Editor</th><th>Action</th><th>Before</th><th>After</th><th>Note</th></tr>")
        for r in log:
            out.append(f"<tr><td>{e(r['created_at'])}</td><td>{e(r['date'])}</td><td>{e(r['editor'])}</td>"
                       f"<td>{e(r['action'])}</td><td>{e(json.dumps(r.get('before'), ensure_ascii=False))}</td>"
                       f"<td>{e(json.dumps(r.get('after'), ensure_ascii=False))}</td><td>{e(r.get('note'))}</td></tr>")
        out.append("</table>")
    out.append("<h2>Editor's checklist (ticked for every approval)</h2><ul>")
    out += [f"<li>{e(label)}</li>" for _, label in EDITOR_CHECKLIST]
    out.append("</ul>")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dates", help="comma-separated; default: every sample edition")
    args = ap.parse_args()
    if args.dates:
        days = sorted({d.strip() for d in args.dates.split(",") if d.strip()})
    else:
        rows = supabase.table("briefing_editions").select("date").eq("is_sample", True).execute().data or []
        days = sorted({r["date"] for r in rows})
    if not days:
        sys.exit("No sample editions found. Run scripts/build_sample_editions.py first.")

    editions = [{"date": d, "items": edition_items(date.fromisoformat(d), publishable_only=False)} for d in days]
    log = supabase.table("briefing_edit_log").select("*").in_("date", days).order("created_at").execute().data or []
    generated = datetime.now(timezone.utc).isoformat(timespec="minutes")
    out = f"briefing_samples_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    os.makedirs(out)
    with open(os.path.join(out, "samples.json"), "w") as f:
        json.dump({"editions": editions, "change_log": log}, f, indent=2, default=str, ensure_ascii=False)
    with open(os.path.join(out, "samples.html"), "w") as f:
        f.write(render(editions, log, generated))

    items = [i for ed in editions for i in ed["items"]]
    by_lane = {lane: sum(1 for i in items if i["lane"] == lane) for lane in LANE_TEXT}
    unapproved = sum(1 for i in items if i["lane"] in ("review", "senior_review") and not i["approved_by"])
    print(f"{len(editions)} editions, {len(items)} items: " + ", ".join(f"{v} {k}" for k, v in by_lane.items())
          + f"; {sum(1 for i in items if i['publishable'])} would publish; {unapproved} held items not yet approved; "
          f"{len(log)} change-log entries")
    print(f"done: {out}/samples.html")


if __name__ == "__main__":
    main()
