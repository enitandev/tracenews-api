from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
from app.db import supabase
from app.routers.auth import get_current_user
import logging

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/reader",
    tags=["reader"]
)

class ConsentRequest(BaseModel):
    granted: bool

import json
import os

# Load consent strings from the single source of truth
json_path = os.path.join(os.path.dirname(__file__), "..", "readerAnalyticsConsent.json")
with open(json_path, "r") as f:
    CONSENT_DATA = json.load(f)

CONSENT_VERSION = CONSENT_DATA["CONSENT_REVIEW"]["version"]
SHOWN_STRINGS = {
    "promise": CONSENT_DATA["TOGGLE"]["promise"],
    "shortNotice": CONSENT_DATA["TOGGLE"]["shortNotice"],
    "refusalIsFree": CONSENT_DATA["TOGGLE"]["refusalIsFree"]
}

@router.post("/consent")
def submit_consent(request: ConsentRequest, user_id: str = Depends(get_current_user)):
    try:
        # Construct the consent receipt
        payload = {
            "user_id": user_id,
            "granted": request.granted,
            "copy_version": CONSENT_VERSION,
            "shown_strings": SHOWN_STRINGS,
            "method": "explicit_toggle",
            "at": datetime.now(timezone.utc).isoformat()
        }
        
        # This table is append-only — never update or delete an existing row,
        # always insert a new one per event.
        supabase.table("reader_analytics_consent").insert(payload).execute()
        
        return {"status": "success", "recorded_event": "granted" if request.granted else "withdrawn"}
    except Exception as e:
        logger.error(f"Failed to record consent for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to record consent")

class TrackReadRequest(BaseModel):
    tier: str
    verdict: str = None

@router.post("/track-read")
def track_read(request: TrackReadRequest, user_id: str = Depends(get_current_user)):
    try:
        # Validate tier
        if request.tier not in ["govt", "mainstream", "watchdog"]:
            raise HTTPException(status_code=400, detail="Invalid tier")
            
        # 1. Check for active consent
        consent_res = supabase.table("reader_analytics_consent") \
            .select("granted") \
            .eq("user_id", user_id) \
            .order("at", desc=True) \
            .limit(1) \
            .execute()
            
        if not consent_res.data or not consent_res.data[0].get("granted"):
            # Return 403, do not track anything
            raise HTTPException(status_code=403, detail="Active consent not found. Tracking aborted.")
            
        # 2. Increment matching counter via upsert pattern (read-modify-write if no RPC)
        counter_column = f"{request.tier}_count"
        
        counter_res = supabase.table("reader_tier_counters") \
            .select("*") \
            .eq("user_id", user_id) \
            .limit(1) \
            .execute()
            
        now_iso = datetime.now(timezone.utc).isoformat()
        
        if counter_res.data:
            current = counter_res.data[0]
            new_count = current.get(counter_column, 0) + 1
            payload = {
                counter_column: new_count,
                "updated_at": now_iso
            }
            if request.verdict == "clear":
                payload["broad_count"] = current.get("broad_count", 0) + 1
            elif request.verdict == "mixed":
                payload["partial_count"] = current.get("partial_count", 0) + 1

            supabase.table("reader_tier_counters").update(payload).eq("user_id", user_id).execute()
        else:
            payload = {
                "user_id": user_id,
                "govt_count": 0,
                "mainstream_count": 0,
                "watchdog_count": 0,
                "broad_count": 0,
                "partial_count": 0,
                counter_column: 1,
                "updated_at": now_iso
            }
            if request.verdict == "clear":
                payload["broad_count"] = 1
            elif request.verdict == "mixed":
                payload["partial_count"] = 1
            supabase.table("reader_tier_counters").insert(payload).execute()
            
        return {"status": "success", "recorded_event": "read_tracked"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to track read for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to track read")

@router.get("/summary")
def get_summary(user_id: str = Depends(get_current_user)):
    try:
        res = supabase.table("reader_tier_counters") \
            .select("govt_count, mainstream_count, watchdog_count, broad_count, partial_count") \
            .eq("user_id", user_id) \
            .limit(1) \
            .execute()
            
        if res.data:
            counts = res.data[0]
            return {
                "govt": counts.get("govt_count", 0),
                "mainstream": counts.get("mainstream_count", 0),
                "watchdog": counts.get("watchdog_count", 0),
                "broad": counts.get("broad_count", 0),
                "partial": counts.get("partial_count", 0)
            }
        else:
            return {
                "govt": 0,
                "mainstream": 0,
                "watchdog": 0,
                "broad": 0,
                "partial": 0
            }
    except Exception as e:
        logger.error(f"Failed to fetch reader summary for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to fetch summary")

@router.delete("/counts")
def delete_counts(user_id: str = Depends(get_current_user)):
    try:
        supabase.table("reader_tier_counters").delete().eq("user_id", user_id).execute()
        return {"status": "success", "recorded_event": "counts_deleted"}
    except Exception as e:
        logger.error(f"Failed to delete reader counts for user {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete counts")
