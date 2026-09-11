import asyncio
from datetime import datetime, timedelta, timezone

async def main():
    try:
        from app.db import supabase
        print("Testing clusters...")
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
        clusters = (
            supabase.table("clusters")
            .select("id, slug, representative_title, created_at, category, coverage_stats")
            .gte("created_at", cutoff)
            .execute()
        ).data or []
        print(f"Got {len(clusters)} clusters")
        if not clusters:
            print("No clusters")
            return
            
        cluster_ids = [c["id"] for c in clusters]
        
        try:
            print("Testing overrides...")
            supabase.table("verdict_overrides").select("cluster_id").eq("active", True).in_("cluster_id", cluster_ids).execute()
        except Exception as e:
            print("Overrides failed!", e)
            
        try:
            print("Testing stories...")
            supabase.table("stories").select("*, story_bias_tags(bias_category_id, source), outlets(slug, name, government_alignment, independence_score, credibility_tier, logo_url, ownership_name, ownership_type, ownership_transparency, party_proximity, track_record_status, promotional_alignment_count, headquarters_city, geopolitical_lean)").in_("cluster_id", cluster_ids).execute()
        except Exception as e:
            print("Stories failed!", e)
            
        try:
            print("Testing snapshots...")
            supabase.table("coverage_snapshots").select("cluster_id, coverage_tier_distribution, outlet_count, snapshot_at").in_("cluster_id", cluster_ids).order("snapshot_at", desc=True).execute()
        except Exception as e:
            print("Snapshots failed!", e)
            
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
