"""Daily Briefing (rebuilt; counsel, 3 Oct 2026, section B).

Public endpoints return 404 while BRIEFING_PUBLIC is off. Staff endpoints
list every item of an edition (with gate and approval) and record a named
editor's approval for items the summary gate holds for review.
"""
import logging
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException

from app.admin_auth import get_actor_name, require_permission
from app.briefing_edition import edition_items, lagos_today, latest_summary
from app.briefingStrings import GATE_NEEDS_EDITOR_APPROVAL, UI
from app.db import supabase
from app.withdrawals import BRIEFING_PUBLIC

logger = logging.getLogger(__name__)

router = APIRouter()


def _require_public():
    if not BRIEFING_PUBLIC:
        raise HTTPException(status_code=404, detail="Not found")


def _latest_published_day():
    """Today's edition, or the most recent one that has something to show."""
    days = supabase.table("briefing_editions").select("date").order("date", desc=True).limit(7).execute().data or []
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


@router.get("/api/admin/briefing")
def staff_edition(day: str = None, _: str = Depends(require_permission("briefing", "view"))):
    d = date.fromisoformat(day) if day else lagos_today()
    return {"date": d.isoformat(), "items": edition_items(d, publishable_only=False), "ui": UI}


@router.post("/api/admin/briefing/{item_id}/approve")
def approve_item(item_id: str, authorization: str = Header(...),
                 _: str = Depends(require_permission("briefing", "edit"))):
    row = (supabase.table("briefing_editions").select("*").eq("id", item_id).limit(1).execute().data or [None])[0]
    if not row:
        raise HTTPException(status_code=404, detail="Not found")
    summary = latest_summary(row["cluster_id"])
    if not summary or summary.get("gate") not in GATE_NEEDS_EDITOR_APPROVAL or summary.get("flags"):
        raise HTTPException(status_code=409, detail="Only an unflagged summary held for review can be approved.")
    editor = get_actor_name(authorization)
    supabase.table("briefing_editions").update({
        "approved_by": editor,
        "approved_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", item_id).execute()
    logger.info(f"[briefing] item {item_id} approved by {editor}")
    return {"status": "approved", "approved_by": editor}
