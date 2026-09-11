from app.db import supabase
try:
    res = supabase.table("reader_tier_counters").select("*").eq("user_id", "123").execute()
    print("User ID test success")
except Exception as e:
    print("User ID Error:", e)

