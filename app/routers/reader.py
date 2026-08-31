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
