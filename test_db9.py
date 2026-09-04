from app.db import supabase
try:
    res = supabase.table("clusters").select("id, slug, representative_title, created_at, category, coverage_stats").limit(1).execute()
    print("Clusters select success")
except Exception as e:
    print("Clusters select error:", e)
