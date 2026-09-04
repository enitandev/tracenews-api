from app.db import supabase
try:
    res = supabase.table("reader_tier_counters").select("govt_count, mainstream_count, watchdog_count, broad_count, partial_count").limit(1).execute()
    print("Counters Select Success")
except Exception as e:
    print("Counters Select Error:", e)
