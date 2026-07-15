from fastapi import APIRouter, Depends, HTTPException, Header
from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime, timedelta
import os
from app.db import supabase

router = APIRouter()

def add_business_days(start: datetime, days: int) -> datetime:
    current = start
    added = 0
    while added < days:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            added += 1
    return current

# --- Public submit ---

class CorrectionSubmit(BaseModel):
    page_url: str
    subject_type: Optional[str] = "other"
    subject_id: Optional[str] = None
    category: str  # identity | data | classification | legal
    description: str
    claimed_correct_info: Optional[str] = None
    source_url: Optional[str] = None
    requester_name: Optional[str] = None
    requester_email: EmailStr
    requester_relationship: Optional[str] = None

@router.post("/api/corrections", status_code=201)
async def submit_correction(payload: CorrectionSubmit):
    res = supabase.table("correction_requests").insert({
        "page_url": payload.page_url,
        "subject_type": payload.subject_type,
        "subject_id": payload.subject_id,
        "category": payload.category,
        "description": payload.description,
        "claimed_correct_info": payload.claimed_correct_info,
        "source_url": payload.source_url,
        "requester_name": payload.requester_name,
        "requester_email": payload.requester_email,
        "requester_relationship": payload.requester_relationship,
        "sla_due_at": add_business_days(datetime.utcnow(), 5).isoformat(),
    }).execute()
    return res.data[0]


# --- Internal admin auth ---
# NOT the reader-facing NDPA auth (unscoped). A separate, lightweight gate
# for internal staff only. Never reuse this mechanism for anything reader-facing.

ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN")  # fail loudly if unset — no default
if not ADMIN_API_TOKEN:
    raise RuntimeError("ADMIN_API_TOKEN is not set")

def require_admin(authorization: Optional[str] = Header(None)):
    if not authorization or authorization != f"Bearer {ADMIN_API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True


# --- Admin queue ---

@router.get("/api/admin/corrections")
async def list_corrections(status: Optional[str] = None, _: bool = Depends(require_admin)):
    query = supabase.table("correction_requests").select("*")
    if status:
        query = query.eq("status", status)
    res = query.order("created_at", desc=True).execute()
    return res.data


class CorrectionUpdate(BaseModel):
    status: Optional[str] = None
    resolution_note: Optional[str] = None
    actor: str  # named person — required, never "admin"

@router.patch("/api/admin/corrections/{correction_id}")
async def update_correction(
    correction_id: str,
    payload: CorrectionUpdate,
    _: bool = Depends(require_admin),
):
    before_res = supabase.table("correction_requests").select("*").eq("id", correction_id).execute()
    if not before_res.data:
        raise HTTPException(status_code=404, detail="Not found")
    before = before_res.data[0]

    updates = {}
    if payload.status:
        updates["status"] = payload.status
        if payload.status in ("actioned", "declined"):
            updates["resolved_at"] = datetime.utcnow().isoformat()
            updates["resolved_by"] = payload.actor
    if payload.resolution_note:
        updates["resolution_note"] = payload.resolution_note

    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    after_res = (
        supabase.table("correction_requests")
        .update(updates)
        .eq("id", correction_id)
        .execute()
    )
    after = after_res.data[0]

    supabase.table("admin_audit_log").insert({
        "actor": payload.actor,
        "action": "correction.update",
        "target_table": "correction_requests",
        "target_id": correction_id,
        "before_state": before,
        "after_state": after,
    }).execute()

    return after
