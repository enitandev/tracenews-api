"""
The Desk's notifications: the bell, the inbox and each person's settings.
Every staff member sees the notifications for the sections their role can
view (app/permissions.py); read state is per person.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel

from app import notifications as n
from app.admin_auth import _staff_identity, get_actor_name, require_permission
from app.db import supabase

router = APIRouter()


def _me(authorization):
    token = authorization.replace("Bearer ", "")
    user_id, profile = _staff_identity(token)
    return token, user_id, profile or {}


@router.get("/api/admin/notifications")
def list_notifications(state: str = "open", authorization: str = Header(...),
                       _: str = Depends(require_permission("console_access", "view"))):
    if state not in ("open", "resolved"):
        raise HTTPException(status_code=400, detail="state is open or resolved")
    _, user_id, profile = _me(authorization)
    items = n.inbox(user_id, profile, get_actor_name(authorization), state)
    counts = n.counts(items) if state == "open" else \
        n.counts(n.inbox(user_id, profile, get_actor_name(authorization), "open"))
    return {"items": items, "counts": counts}


class ReadBody(BaseModel):
    ids: Optional[List[str]] = None
    all: bool = False


@router.post("/api/admin/notifications/read")
def mark_read(body: ReadBody, authorization: str = Header(...),
              _: str = Depends(require_permission("console_access", "view"))):
    _, user_id, profile = _me(authorization)
    if body.all:
        ids = [i["id"] for i in n.inbox(user_id, profile, get_actor_name(authorization), "open") if not i["read"]]
    else:
        ids = body.ids or []
    return {"marked": n.mark_read(user_id, ids)}


@router.post("/api/admin/notifications/{notification_id}/clear")
def clear(notification_id: str, authorization: str = Header(...),
          _: str = Depends(require_permission("console_access", "view"))):
    """Clear a one-off event (an AI-provider refusal) once it is dealt with.
    Conditions with state (an open correction, a late feed) clear themselves
    when the condition does; clearing them by hand would only hide them."""
    rows = supabase.table(n.TABLE).select("*").eq("id", notification_id).limit(1).execute().data or []
    if not rows:
        raise HTTPException(status_code=404, detail="Not found")
    row = rows[0]
    _, _, profile = _me(authorization)
    if not n.visible(row, profile):
        raise HTTPException(status_code=404, detail="Not found")
    if not (row.get("meta") or {}).get("event"):
        raise HTTPException(status_code=400, detail="This clears itself when the underlying problem is fixed.")
    if row.get("resolved_at"):
        return row
    n.resolve(row["dedupe_key"], by=get_actor_name(authorization))
    return {**row, "resolved_by": get_actor_name(authorization)}


class Prefs(BaseModel):
    email_urgent: bool


@router.get("/api/admin/notifications/prefs")
def get_prefs(authorization: str = Header(...), _: str = Depends(require_permission("console_access", "view"))):
    _, user_id, _ = _me(authorization)
    rows = supabase.table(n.PREFS).select("email, email_urgent").eq("user_id", user_id).limit(1).execute().data or []
    return rows[0] if rows else {"email": None, "email_urgent": False}


@router.put("/api/admin/notifications/prefs")
def put_prefs(body: Prefs, authorization: str = Header(...),
              _: str = Depends(require_permission("console_access", "view"))):
    """Urgent emails go to the address this person signs in with, taken from
    their session when they turn the setting on."""
    token, user_id, _ = _me(authorization)
    email = supabase.auth.get_user(token).user.email
    row = {"user_id": user_id, "email": email, "email_urgent": body.email_urgent,
           "updated_at": n._iso(n._now())}
    supabase.table(n.PREFS).upsert(row, on_conflict="user_id").execute()
    return {"email": email, "email_urgent": body.email_urgent}
