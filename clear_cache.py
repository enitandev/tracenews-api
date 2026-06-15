import sys
import os

sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app.db import supabase

# In python postgrest, we can't do raw SQL updates easily, but we can do:
# update({"framing_cache": {}}).neq("framing_cache", "{}") # Wait, how to check IS NOT NULL?
# We can just fetch all clusters with framing_cache != '{}' and update them.
res = supabase.table("clusters").select("id, framing_cache").execute()
clusters = res.data or []
updated = 0
for c in clusters:
    fc = c.get("framing_cache")
    if fc is not None and fc != {}:
        supabase.table("clusters").update({"framing_cache": {}}).eq("id", c["id"]).execute()
        updated += 1

print(f"Cleared cache for {updated} clusters.")
