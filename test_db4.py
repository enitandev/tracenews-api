from app.db import supabase
try:
    res = supabase.table("reader_tier_counters").select("updated_at").limit(1).execute()
    print("updated_at Success")
except Exception as e:
    print("updated_at Error:", e)

