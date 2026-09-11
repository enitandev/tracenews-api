from app.db import supabase
try:
    stories_res = supabase.table("stories").select(
        "*, story_bias_tags(bias_category_id, source), outlets(slug, name, government_alignment, independence_score, credibility_tier, logo_url, ownership_name, ownership_type, ownership_transparency, party_proximity, track_record_status, promotional_alignment_count, headquarters_city, geopolitical_lean)"
    ).limit(1).execute()
    print("Stories select success")
except Exception as e:
    print("Stories select error:", e)
