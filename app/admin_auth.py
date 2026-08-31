import os
from fastapi import Header, HTTPException, Depends
from app.db import supabase

def require_staff(authorization: str = Header(...)):
    """
    Validates a real Supabase session token AND checks the profiles.is_staff
    flag. Replaces the old shared ADMIN_API_TOKEN mechanism entirely.
    """
    token = authorization.replace("Bearer ", "")
    user_res = supabase.auth.get_user(token)
    if not user_res or not user_res.user:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    profile_res = (
        supabase.table("profiles")
        .select("is_staff")
        .eq("id", user_res.user.id)
        .execute()
    )
    if not profile_res.data or not profile_res.data[0].get("is_staff"):
        raise HTTPException(status_code=403, detail="Staff access required")

    return user_res.user.id  # return the real user id, not just True


def get_actor_name(user_id: str = Depends(require_staff)) -> str:
    """
    Resolves the authenticated staff user's display name, for use as the
    'actor' field in admin_audit_log — so audit entries are tied to the
    real logged-in person, not a free-text field someone could type
    anything into.
    """
    profile_res = supabase.table("profiles").select("display_name").eq("id", user_id).execute()
    name = (profile_res.data[0].get("display_name") if profile_res.data else None)
    return name or user_id  # fall back to user_id if no display_name set
