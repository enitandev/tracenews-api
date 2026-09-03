import os
from fastapi import Header, HTTPException, Depends
from app.db import supabase
from app.permissions import has_permission, is_staff_role

def require_permission(section: str, action: str = "view"):
    def dependency(authorization: str = Header(...)):
        token = authorization.replace("Bearer ", "")
        user_res = supabase.auth.get_user(token)
        if not user_res or not user_res.user:
            raise HTTPException(status_code=401, detail="Invalid or expired session")

        profile_res = (
            supabase.table("profiles")
            .select("role, is_staff")
            .eq("id", user_res.user.id)
            .execute()
        )
        if not profile_res.data:
            raise HTTPException(status_code=403, detail="Staff access required")
            
        profile = profile_res.data[0]
        if not has_permission(profile.get("role"), profile.get("is_staff"), section, action):
            raise HTTPException(status_code=403, detail="Permission denied")

        return user_res.user.id
    return dependency

def get_actor_name(authorization: str = Header(...)) -> str:
    token = authorization.replace("Bearer ", "")
    user_res = supabase.auth.get_user(token)
    if not user_res or not user_res.user:
        return "Unknown"
        
    user_id = user_res.user.id
    profile_res = supabase.table("profiles").select("display_name, role, is_staff").eq("id", user_id).execute()
    if profile_res.data:
        p = profile_res.data[0]
        name = p.get("display_name") or user_id
        role = p.get("role")
        if not role:
            role = "legacy_staff" if p.get("is_staff") else "unknown"
        return f"{name} ({role})"
    return user_id
