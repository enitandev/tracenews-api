import sys
import os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
from app.db import supabase

res = supabase.table("clusters").select("id, framing_cache").neq("framing_cache", "{}").execute()
clusters = res.data or []
updated = 0
for c in clusters:
    if c.get("framing_cache"):
        supabase.table("clusters").update({"framing_cache": {}}).eq("id", c["id"]).execute()
        updated += 1

print(f"Cleared cache for {updated} clusters.")
