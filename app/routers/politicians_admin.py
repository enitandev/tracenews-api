from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.admin_auth import require_admin
from app.db import supabase

router = APIRouter()


@router.get("/api/admin/politicians")
async def list_by_status(status: str = "pending_review", _: bool = Depends(require_admin)):
    """
    status: 'pending_review' | 'excluded' | 'published'
    Defaults to pending_review — the working queue.
    """
    if status not in ("pending_review", "excluded", "published"):
        raise HTTPException(status_code=400, detail="Invalid status filter")

    res = (
        supabase.table("politicians")
        .select("id, slug, full_name, category, publication_status, updated_at")
        .eq("publication_status", status)
        .order("full_name")
        .execute()
    )
    # Rename full_name to name for frontend
    for row in res.data:
        row["name"] = row.pop("full_name", "Unknown")
    return res.data


class StatusUpdate(BaseModel):
    publication_status: str  # 'published' | 'excluded' | 'pending_review'
    reason: str              # required — cite the addendum disposition or new basis
    actor: str                # named person, required

@router.patch("/api/admin/politicians/{politician_id}")
async def update_status(politician_id: str, payload: StatusUpdate, _: bool = Depends(require_admin)):
    if payload.publication_status not in ("published", "excluded", "pending_review"):
        raise HTTPException(status_code=400, detail="Invalid publication_status")
    if not payload.reason.strip():
        raise HTTPException(status_code=400, detail="Reason is required")
    if not payload.actor.strip():
        raise HTTPException(status_code=400, detail="Actor is required")

    before_res = supabase.table("politicians").select("*").eq("id", politician_id).execute()
    if not before_res.data:
        raise HTTPException(status_code=404, detail="Not found")
    before = before_res.data[0]

    after_res = (
        supabase.table("politicians")
        .update({"publication_status": payload.publication_status})
        .eq("id", politician_id)
        .execute()
    )
    after = after_res.data[0]

    supabase.table("admin_audit_log").insert({
        "actor": payload.actor,
        "action": "politician.status_change",
        "target_table": "politicians",
        "target_id": politician_id,
        "before_state": {"publication_status": before["publication_status"], "reason": payload.reason},
        "after_state": {"publication_status": after["publication_status"]},
    }).execute()

    return after


@router.get("/api/admin/politicians/{politician_id}/history")
async def get_history(politician_id: str, _: bool = Depends(require_admin)):
    """Full audit trail for one politician — every status change, who, when, why."""
    res = (
        supabase.table("admin_audit_log")
        .select("*")
        .eq("target_table", "politicians")
        .eq("target_id", politician_id)
        .order("created_at", desc=True)
        .execute()
    )
    return res.data
