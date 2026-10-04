import logging
import os
import time
from fastapi import Header, HTTPException, Depends
from app.db import supabase
from app.permissions import has_permission, is_staff_role

logger = logging.getLogger(__name__)

# A staff request used to validate the session token with Supabase and read
# the profile on every call (two network round trips; four for an approval,
# which also names the editor). The result is kept for a minute per token.
IDENTITY_TTL_SECONDS = 60
_identities = {}         # token -> (expires_at, user_id, profile or None)


def _staff_identity(token):
    """(user_id, profile) for a session token, or HTTP 401 if it is not valid."""
    now = time.time()
    hit = _identities.get(token)
    if hit and hit[0] > now:
        return hit[1], hit[2]
    try:
        user_res = supabase.auth.get_user(token)
    except Exception:
        # The auth client raises on a malformed or expired token; that is
        # a rejected session (401), not a server error.
        logger.warning("Rejected staff request: session token could not be validated")
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    user_id = user_res.user.id
    rows = supabase.table("profiles").select("display_name, role, is_staff").eq("id", user_id).execute().data
    profile = rows[0] if rows else None
    if len(_identities) > 1000:
        _identities.clear()
    _identities[token] = (now + IDENTITY_TTL_SECONDS, user_id, profile)
    return user_id, profile


def require_permission(section: str, action: str = "view"):
    def dependency(authorization: str = Header(...)):
        user_id, profile = _staff_identity(authorization.replace("Bearer ", ""))
        if not profile:
            raise HTTPException(status_code=403, detail="Staff access required")
        if not has_permission(profile.get("role"), profile.get("is_staff"), section, action):
            raise HTTPException(status_code=403, detail="Permission denied")
        return user_id
    return dependency


def get_actor_name(authorization: str = Header(...)) -> str:
    try:
        user_id, p = _staff_identity(authorization.replace("Bearer ", ""))
    except HTTPException:
        return "Unknown"
    if p:
        name = p.get("display_name") or user_id
        role = p.get("role")
        if not role:
            role = "legacy_staff" if p.get("is_staff") else "unknown"
        return f"{name} ({role})"
    return user_id
