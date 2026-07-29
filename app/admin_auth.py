import os
from fastapi import Header, HTTPException

ADMIN_API_TOKEN = os.environ.get("ADMIN_API_TOKEN")  # fail loudly if unset
if not ADMIN_API_TOKEN:
    raise RuntimeError("ADMIN_API_TOKEN is not set")

def require_admin(authorization: str = Header(None)):
    if not authorization or authorization != f"Bearer {ADMIN_API_TOKEN}":
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True
