"""Daily Briefing (rebuilt; counsel, 3 Oct 2026, section B, amended by
counsel's review of the 3 Oct samples).

Public endpoints return 404 while BRIEFING_PUBLIC is off, and never show
sample editions. Staff endpoints list every item of an edition with its
routing, let a named editor rewrite, leave out, restore or approve an item,
and write every such action to briefing_edit_log.
"""
import logging
import re
from datetime import date, datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app.admin_auth import get_actor_name, require_permission
from app.briefing_edition import (
    clean_headline, edition_items, first_approval_valid, has_forbidden_token, headline_problems, item_lane, lagos_today,
)
from app.briefing_extras import check_extras, section_texts
from app.briefingStrings import EDITOR_CHECKLIST, LANE_SENIOR_REVIEW, LANES_NEEDING_EDITOR, SENIOR_SECOND_APPROVERS, UI
from app.storySummaryStrings import SUMMARY_MAX_BULLETS
from app.summarizer import cluster_articles_text
from app.db import supabase
from app.withdrawals import BRIEFING_PUBLIC

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_public():
    if not BRIEFING_PUBLIC:
        raise HTTPException(status_code=404, detail="Not found")


def _latest_published_day():
    """Today's edition, or the most recent one that has something to show."""
    days = supabase.table("briefing_editions").select("date").eq("is_sample", False) \
        .order("date", desc=True).limit(7).execute().data or []
    for d in sorted({r["date"] for r in days}, reverse=True):
        day = date.fromisoformat(d)
        if day <= lagos_today() and edition_items(day):
            return day
    return None


@router.get("/daily-briefing")
def get_daily_briefing():
    _require_public()
    day = _latest_published_day()
    if not day:
        return {"date": None, "items": [], "message": UI["empty"], "ui": UI}
    return {"date": day.isoformat(), "items": edition_items(day), "ui": UI}


@router.get("/daily-briefing/{slug}")
def get_daily_briefing_story(slug: str):
    _require_public()
    day = _latest_published_day()
    item = next((i for i in (edition_items(day) if day else []) if i["slug"] == slug), None)
    if not item:
        raise HTTPException(status_code=404, detail="Not found")
    return {"date": day.isoformat(), "item": item, "ui": UI}


# ═══ STAFF ═══════════════════════════════════════════════════════════════════

CHECKLIST = [{"key": k, "label": label} for k, label in EDITOR_CHECKLIST]
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _named_editor(authorization):
    """The acting editor's display name and role. Editor actions need a name."""
    actor = get_actor_name(authorization)
    name = actor.split(" (")[0]
    if actor == "Unknown" or _UUID.match(name):
        raise HTTPException(status_code=403, detail="Editor actions need a named editor: set a display name on your staff profile.")
    return actor


def _row(item_id):
    row = (supabase.table("briefing_editions").select("*").eq("id", item_id).limit(1).execute().data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    return row


def _log(row, editor, action, before=None, after=None, note=None):
    supabase.table("briefing_edit_log").insert({
        "edition_id": row["id"], "date": row["date"], "cluster_id": row["cluster_id"],
        "is_sample": bool(row.get("is_sample")), "editor": editor, "action": action,
        "before": before, "after": after, "note": note,
    }).execute()


def _now():
    return datetime.now(timezone.utc).isoformat()


@router.get("/api/admin/briefing")
def staff_edition(day: str = None, _: str = Depends(require_permission("briefing", "view"))):
    d = date.fromisoformat(day) if day else lagos_today()
    return {"date": d.isoformat(), "items": edition_items(d, publishable_only=False),
            "checklist": CHECKLIST, "ui": UI}


@router.get("/api/admin/briefing/dates")
def staff_edition_dates(_: str = Depends(require_permission("briefing", "view"))):
    """Dates that have an edition, newest first, with item counts and whether it is a sample."""
    rows = supabase.table("briefing_editions").select("date, is_sample") \
        .order("date", desc=True).limit(1000).execute().data or []
    dates = {}
    for r in rows:
        d = dates.setdefault(r["date"], {"date": r["date"], "is_sample": bool(r.get("is_sample")), "items": 0})
        d["items"] += 1
    return {"dates": list(dates.values())}


class Quote(BaseModel):
    speaker: str
    role: str
    quote: str


class Sections(BaseModel):
    quotes: List[Quote] = []
    next: List[str] = []
    background: List[str] = []


class Rewrite(BaseModel):
    title: Optional[str] = None
    bullets: Optional[List[str]] = None
    sections: Optional[Sections] = None
    note: Optional[str] = None


@router.post("/api/admin/briefing/{item_id}/rewrite")
def rewrite_item(item_id: str, body: Rewrite, authorization: str = Header(...),
                 _: str = Depends(require_permission("briefing", "edit"))):
    editor = _named_editor(authorization)
    row = _row(item_id)
    title = body.title.strip() if body.title is not None else row.get("edited_title")
    bullets = [b.strip() for b in body.bullets if b.strip()] if body.bullets is not None else row.get("edited_bullets")
    if bullets is not None and not 1 <= len(bullets) <= SUMMARY_MAX_BULLETS:
        raise HTTPException(status_code=422, detail=f"What happened has 1 to {SUMMARY_MAX_BULLETS} points.")
    sections = row.get("edited_extras")
    if body.sections is not None:
        # The editor's sections pass the same checks as generated ones:
        # quotes verbatim in the sources, attributed next steps, limits.
        raw = body.sections.model_dump()
        sections, dropped = check_extras(raw, cluster_articles_text(row["cluster_id"]))
        if dropped:
            raise HTTPException(status_code=422, detail="Not saved: " + " | ".join(dropped))
    section_text = section_texts(sections or {})
    token = has_forbidden_token([title or ""] + (bullets or []) + section_text)
    if token:
        raise HTTPException(status_code=422, detail=f"The rewrite contains a forbidden word: {token}")
    if title:
        problems = headline_problems(clean_headline(title), (bullets or []) + section_text)
        if problems:
            raise HTTPException(status_code=422, detail="The headline does not pass the headline checks: " + "; ".join(problems))
    before = {"title": row.get("edited_title"), "bullets": row.get("edited_bullets"), "sections": row.get("edited_extras")}
    after = {"title": title or None, "bullets": bullets or None, "sections": sections or None}
    if before == after:
        raise HTTPException(status_code=409, detail="Nothing changed.")
    _log(row, editor, "rewrite", before, after, body.note)
    supabase.table("briefing_editions").update({
        "edited_title": after["title"], "edited_bullets": after["bullets"], "edited_extras": after["sections"],
        "edited_by": editor, "edited_at": _now(),
    }).eq("id", item_id).execute()
    logger.info(f"[briefing] item {item_id} rewritten by {editor}")
    return {"status": "rewritten", "edited_by": editor}


class LeaveOut(BaseModel):
    reason: str


@router.post("/api/admin/briefing/{item_id}/leave-out")
def leave_out_item(item_id: str, body: LeaveOut, authorization: str = Header(...),
                   _: str = Depends(require_permission("briefing", "edit"))):
    editor = _named_editor(authorization)
    if not body.reason.strip():
        raise HTTPException(status_code=422, detail="Give a reason for leaving the item out.")
    row = _row(item_id)
    _log(row, editor, "leave_out", None, None, body.reason.strip())
    supabase.table("briefing_editions").update({
        "left_out_by": editor, "left_out_reason": body.reason.strip(), "left_out_at": _now(),
    }).eq("id", item_id).execute()
    return {"status": "left_out", "left_out_by": editor}


@router.post("/api/admin/briefing/{item_id}/restore")
def restore_item(item_id: str, authorization: str = Header(...),
                 _: str = Depends(require_permission("briefing", "edit"))):
    editor = _named_editor(authorization)
    row = _row(item_id)
    if not row.get("left_out_by"):
        raise HTTPException(status_code=409, detail="The item was not left out.")
    _log(row, editor, "restore", {"left_out_by": row["left_out_by"], "reason": row.get("left_out_reason")}, None)
    supabase.table("briefing_editions").update({
        "left_out_by": None, "left_out_reason": None, "left_out_at": None,
    }).eq("id", item_id).execute()
    return {"status": "restored"}


class PartyCheck(BaseModel):
    descriptor: str      # e.g. "Atiku Abubakar, ADC presidential candidate"
    source: str          # where it was checked (URL or named source)
    checked_at: str      # when it was checked


class Approval(BaseModel):
    checklist: Dict[str, bool]
    party_checks: List[PartyCheck] = []
    no_party_descriptors: bool = False
    note: Optional[str] = None


@router.post("/api/admin/briefing/{item_id}/approve")
def approve_item(item_id: str, body: Approval, authorization: str = Header(...),
                 _: str = Depends(require_permission("briefing", "edit"))):
    """First approval for review and senior review; a second, different
    approver for senior review (counsel's ruling, 3 Oct, item 5). The
    party_live line needs the source and time checked for each descriptor."""
    editor = _named_editor(authorization)
    missing = [label for key, label in EDITOR_CHECKLIST if not body.checklist.get(key)]
    if missing:
        raise HTTPException(status_code=422, detail="Tick every checklist line before approving: " + " | ".join(missing))
    checks = [c for c in body.party_checks if c.descriptor.strip() and c.source.strip() and c.checked_at.strip()]
    if len(checks) != len(body.party_checks) or (not checks and not body.no_party_descriptors):
        raise HTTPException(status_code=422, detail="For each party or candidacy descriptor, enter the descriptor, the source and the time you checked it, or confirm the item has none.")
    row = _row(item_id)
    lane, summary = item_lane(row)
    if lane not in LANES_NEEDING_EDITOR:
        raise HTTPException(status_code=409, detail=f"Only an item held for review can be approved (this item: {lane}).")
    record = {"checklist": {k: True for k, _ in EDITOR_CHECKLIST},
              "party_checks": [c.model_dump() for c in checks], "no_party_descriptors": body.no_party_descriptors and not checks}
    approved_text = {"title": row.get("edited_title"), "bullets": row.get("edited_bullets") or (summary or {}).get("bullets"),
                     "sections": row.get("edited_extras") or row.get("extras"), "summary_id": str(summary["id"]), **record}

    if first_approval_valid(row, summary):
        if lane != LANE_SENIOR_REVIEW:
            raise HTTPException(status_code=409, detail=f"Already approved by {row['approved_by']}.")
        if row.get("second_approved_by"):
            raise HTTPException(status_code=409, detail=f"Already approved by {row['approved_by']} and {row['second_approved_by']}.")
        if editor == row["approved_by"]:
            raise HTTPException(status_code=409, detail="Senior review needs a second approver who is not the first editor.")
        if editor.split(" (")[0] not in SENIOR_SECOND_APPROVERS:
            raise HTTPException(status_code=403, detail="The second approval for senior-review items is given by: " + ", ".join(SENIOR_SECOND_APPROVERS) + ".")
        _log(row, editor, "approve_second", None, approved_text, body.note)
        supabase.table("briefing_editions").update({
            "second_approved_by": editor, "second_approved_at": _now(),
        }).eq("id", item_id).execute()
        logger.info(f"[briefing] item {item_id} second approval by {editor}")
        return {"status": "approved", "approved_by": row["approved_by"], "second_approved_by": editor}

    _log(row, editor, "approve", None, approved_text, body.note)
    supabase.table("briefing_editions").update({
        "approved_by": editor,
        "approved_at": _now(),
        "approved_summary_id": str(summary["id"]),
        "approved_edit_at": row.get("edited_at"),
        "approval_checklist": record,
        "second_approved_by": None,
        "second_approved_at": None,
    }).eq("id", item_id).execute()
    logger.info(f"[briefing] item {item_id} approved by {editor}")
    return {"status": "approved", "approved_by": editor,
            "needs_second_approver": lane == LANE_SENIOR_REVIEW}


@router.get("/api/admin/briefing/log")
def edit_log(since: str = None, until: str = None, _: str = Depends(require_permission("briefing", "view"))):
    q = supabase.table("briefing_edit_log").select("*")
    if since:
        q = q.gte("created_at", since)
    if until:
        q = q.lt("created_at", until)
    return {"entries": q.order("created_at").execute().data or []}

