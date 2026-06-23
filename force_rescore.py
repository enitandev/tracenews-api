from datetime import datetime, timezone, timedelta
from app.db import supabase

slugs = ['bbc-hausa', 'bbc-yoruba', 'rfi-hausa', 'aminiya']
cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

for slug in slugs:
    supabase.table("outlet_behavioral_scores").delete().eq("outlet_slug", slug).gte("analyzed_at", cutoff).execute()
    print(f"Deleted recent scores for {slug}")
