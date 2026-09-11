import asyncio
from app.routers.monitoring_spirit_admin import list_current_verdicts

async def main():
    try:
        from app.db import supabase
        print("Testing clusters...")
        clusters = (
            supabase.table("clusters")
            .select("id, slug, representative_title, created_at, category, coverage_stats")
            .gte("created_at", "2024-01-01T00:00:00Z")
            .limit(2)
            .execute()
        ).data or []
        print(f"Got {len(clusters)} clusters")
        if not clusters:
            print("No clusters")
            return
            
        cluster_ids = [c["id"] for c in clusters]
        print("Testing overrides with", cluster_ids)
        supabase.table("verdict_overrides").select("cluster_id").eq("active", True).in_("cluster_id", cluster_ids).execute()
        print("Overrides success")
        
        print("Testing stories...")
        supabase.table("stories").select("*, story_bias_tags(bias_category_id, source), outlets(slug, name, government_alignment, independence_score, credibility_tier, logo_url, ownership_name, ownership_type, ownership_transparency, party_proximity, track_record_status, promotional_alignment_count, headquarters_city, geopolitical_lean)").in_("cluster_id", cluster_ids).execute()
        print("Stories success")
        
        print("Testing snapshots...")
        supabase.table("coverage_snapshots").select("cluster_id, coverage_tier_distribution, outlet_count, snapshot_at").in_("cluster_id", cluster_ids).order("snapshot_at", desc=True).execute()
        print("Snapshots success")
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
