"""
The Desk: one call for the console's overview, the rail counts and platform
health. Every figure is measured from the database; nothing is a fixed label.
"""
import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header

from app.admin_auth import get_actor_name, require_permission
from app.briefing_edition import is_senior_approver, lagos_today
from app.db import supabase

logger = logging.getLogger(__name__)
router = APIRouter()

OPEN_CORRECTION_STATUSES = ("new", "in_review", "escalated_legal")
# A stage is "late" when its newest record is older than this (the worker
# runs every 20 minutes; summaries follow new stories).
FEED_LATE_MINUTES = 60
WORKER_LATE_MINUTES = 45


def _age_minutes(iso):
    if not iso:
        return None
    t = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    return round((datetime.now(timezone.utc) - t).total_seconds() / 60)


def _latest(table, column):
    rows = supabase.table(table).select(column).order(column, desc=True).limit(1).execute().data or []
    return rows[0][column] if rows else None


def is_mine(item, me):
    """Whether this editor can give the approval an item is waiting for."""
    first = item.get("approved_by")
    if not first:
        return True
    return bool(item.get("needs_second_approver")) and first != me \
        and is_senior_approver(me) != is_senior_approver(first)


def briefing_waiting(items, me):
    """Held items not yet publishable, and the ones this editor can act on."""
    waiting = [i for i in items
               if i.get("lane") in ("review", "senior_review") and not i.get("publishable") and not i.get("left_out_by")]
    return waiting, [i for i in waiting if is_mine(i, me)]


def _health():
    feed = _latest("stories", "created_at")
    summary = _latest("cluster_summaries", "generated_at")
    worker = (supabase.table("public_feeds").select("computed_at").eq("feed_key", "monitoring_spirit_verdicts")
              .limit(1).execute().data or [{}])[0].get("computed_at")
    rows = [
        {"key": "feed", "label": "Newest story", "minutes": _age_minutes(feed),
         "late": (_age_minutes(feed) or 10**6) > FEED_LATE_MINUTES},
        {"key": "worker", "label": "Worker last run", "minutes": _age_minutes(worker),
         "late": (_age_minutes(worker) or 10**6) > WORKER_LATE_MINUTES},
        {"key": "summaries", "label": "Newest summary", "minutes": _age_minutes(summary), "late": False},
    ]
    return rows, os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown")[:7]


def _ledger():
    """The latest staff actions from the audit log and the Briefing change log."""
    audit = supabase.table("admin_audit_log").select("actor, action, target_table, before_state, after_state, created_at") \
        .order("created_at", desc=True).limit(8).execute().data or []
    edits = supabase.table("briefing_edit_log").select("editor, action, note, date, created_at") \
        .neq("editor", "system").order("created_at", desc=True).limit(8).execute().data or []
    entries = []
    for a in audit:
        reason = (a.get("before_state") or {}).get("reason") or (a.get("after_state") or {}).get("reason")
        entries.append({"actor": a.get("actor"), "action": (a.get("action") or "").replace("_", " ").replace(".", " · "),
                        "subject": a.get("target_table"), "reason": reason, "at": a.get("created_at")})
    for e in edits:
        entries.append({"actor": e.get("editor"), "action": (e.get("action") or "").replace("_", " "),
                        "subject": f"Briefing {e.get('date')}", "reason": e.get("note"), "at": e.get("created_at")})
    entries.sort(key=lambda x: x["at"] or "", reverse=True)
    return entries[:8]


@router.get("/api/admin/desk")
def desk(authorization: str = Header(...), _: str = Depends(require_permission("console_access", "view"))):
    me = get_actor_name(authorization)
    now = datetime.now(timezone.utc)

    corrections = supabase.table("correction_requests") \
        .select("id, category, subject_type, subject_id, page_url, status, sla_due_at, created_at") \
        .in_("status", list(OPEN_CORRECTION_STATUSES)).order("sla_due_at").limit(200).execute().data or []
    overdue = [c for c in corrections if c.get("sla_due_at") and c["sla_due_at"] < now.isoformat()]

    held = supabase.table("politicians").select("id", count="exact").eq("publication_status", "pending_review") \
        .limit(1).execute()
    feed = (supabase.table("public_feeds").select("payload").eq("feed_key", "monitoring_spirit_verdicts")
            .limit(1).execute().data or [{}])[0].get("payload") or []

    from app.routers.briefing import staff_items
    today = lagos_today()
    try:
        items = staff_items(today)
    except Exception:
        logger.exception("[desk] could not load today's Briefing")
        items = None
    waiting, mine = briefing_waiting(items or [], me)
    health, version = _health()

    return {
        "me": me,
        "date": today.isoformat(),
        "counts": {
            "corrections_open": len(corrections),
            "corrections_overdue": len(overdue),
            "politicians_held": held.count or 0,
            "verdicts": len(feed),
            "verdicts_dark": sum(1 for v in feed if v.get("verdict") == "dark"),
            "briefing_items": None if items is None else len(items),
            "briefing_waiting": len(waiting),
            "briefing_waiting_me": len(mine),
        },
        "queue": {
            "briefing": [{"id": i["id"], "title": i.get("title"), "lane": i.get("lane"),
                          "approved_by": i.get("approved_by"), "waiting_for": i.get("waiting_for"),
                          "mine": i in mine} for i in waiting],
            "corrections": [{**c, "overdue": c in overdue} for c in corrections[:6]],
        },
        "health": health,
        "version": version,
        "ledger": _ledger(),
    }
