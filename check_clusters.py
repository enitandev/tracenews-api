import asyncio
from app.db import supabase
res = supabase.table("clusters").select("coverage_stats, representative_title").order("created_at", desc=True).limit(5).execute()
print(res.data)
