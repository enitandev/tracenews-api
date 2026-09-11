import os

with open("app/main.py", "r") as f:
    content = f.read()

new_endpoints = """
@app.get("/daily-briefing")
def get_daily_briefing():
    from datetime import datetime, timezone, timedelta
    
    lagos_now = datetime.now(timezone.utc) + timedelta(hours=1)
    today = lagos_now.date().isoformat()
    
    rows_res = supabase.table("daily_briefings")\\
        .select("id, date, cluster_id, cluster_slug, position, generation_status, perspectives_title, ground_summary")\\
        .eq("date", today)\\
        .eq("generation_status", "complete")\\
        .order("position")\\
        .execute()
    
    rows = rows_res.data or []
    
    if not rows:
        return {
            "date": today,
            "status": "no_briefing",
            "stories": []
        }
    
    # Enrich each row with cluster data (image, outlet_count, category)
    cluster_ids = [r["cluster_id"] for r in rows]
    
    clusters_res = supabase.table("clusters")\\
        .select("id, slug, representative_title, outlet_count, category, first_seen_at, coverage_stats, stories(image_url)")\\
        .in_("id", cluster_ids)\\
        .execute()
    
    clusters_map = {c["id"]: c for c in (clusters_res.data or [])}
    
    stories = []
    for row in rows:
        cluster = clusters_map.get(row["cluster_id"], {})
        
        # Get first available image
        image_url = None
        for s in (cluster.get("stories") or []):
            if s.get("image_url"):
                image_url = s["image_url"]
                break
        
        stories.append({
            "position": row["position"],
            "cluster_slug": row["cluster_slug"],
            "perspectives_title": row.get("perspectives_title"),
            "ground_summary": row.get("ground_summary"),
            "representative_title": cluster.get("representative_title"),
            "outlet_count": cluster.get("outlet_count"),
            "category": cluster.get("category"),
            "first_seen_at": cluster.get("first_seen_at"),
            "coverage_stats": cluster.get("coverage_stats"),
            "image_url": image_url
        })
    
    return {
        "date": today,
        "status": "ready",
        "stories": stories
    }

@app.get("/daily-briefing/{slug}")
def get_daily_briefing_story(slug: str):
    from datetime import datetime, timezone, timedelta
    from fastapi import HTTPException
    
    lagos_now = datetime.now(timezone.utc) + timedelta(hours=1)
    today = lagos_now.date().isoformat()
    
    # Find the briefing row for this slug
    row_res = supabase.table("daily_briefings")\\
        .select("*")\\
        .eq("cluster_slug", slug)\\
        .eq("generation_status", "complete")\\
        .order("date", desc=True)\\
        .limit(1)\\
        .execute()
    
    if not row_res.data:
        raise HTTPException(
            status_code=404,
            detail="Briefing not found for this story"
        )
    
    row = row_res.data[0]
    
    # Get full cluster data including stories with outlet info
    cluster_res = supabase.table("clusters")\\
        .select("id, slug, representative_title, outlet_count, category, first_seen_at, last_updated_at, coverage_stats")\\
        .eq("id", row["cluster_id"])\\
        .execute()
    
    cluster = cluster_res.data[0] if cluster_res.data else {}
    
    # Get stories with outlet data for Bias Distribution sidebar
    stories_res = supabase.table("stories")\\
        .select("id, title, url, outlet_slug, published_at, image_url, outlets(slug, name, logo_url, independence_score, credibility_tier, government_alignment)")\\
        .eq("cluster_id", row["cluster_id"])\\
        .order("published_at")\\
        .execute()
    
    stories = stories_res.data or []
    
    # Get first available image
    image_url = None
    for s in stories:
        if s.get("image_url"):
            image_url = s["image_url"]
            break
    
    # Get "More from Today's Briefing"
    other_rows_res = supabase.table("daily_briefings")\\
        .select("position, cluster_slug, perspectives_title, ground_summary")\\
        .eq("date", row["date"])\\
        .eq("generation_status", "complete")\\
        .neq("cluster_slug", slug)\\
        .order("position")\\
        .execute()
    
    other_rows = other_rows_res.data or []
    
    # Enrich other rows with cluster data
    if other_rows:
        other_cluster_slugs = [r["cluster_slug"] for r in other_rows]
        other_clusters_res = supabase.table("clusters")\\
            .select("slug, representative_title, outlet_count, category, coverage_stats, stories(image_url)")\\
            .in_("slug", other_cluster_slugs)\\
            .execute()
        
        other_clusters_map = {c["slug"]: c for c in (other_clusters_res.data or [])}
        
        more_from_briefing = []
        for r in other_rows:
            oc = other_clusters_map.get(r["cluster_slug"], {})
            img = None
            for s in (oc.get("stories") or []):
                if s.get("image_url"):
                    img = s["image_url"]
                    break
            more_from_briefing.append({
                "cluster_slug": r["cluster_slug"],
                "perspectives_title": r.get("perspectives_title"),
                "representative_title": oc.get("representative_title"),
                "outlet_count": oc.get("outlet_count"),
                "category": oc.get("category"),
                "coverage_stats": oc.get("coverage_stats"),
                "image_url": img
            })
    else:
        more_from_briefing = []
    
    return {
        "date": row["date"],
        "position": row["position"],
        "cluster": cluster,
        "image_url": image_url,
        "stories": stories,
        "ground_summary": row.get("ground_summary"),
        "common_ground": row.get("common_ground"),
        "perspectives_title": row.get("perspectives_title"),
        "perspectives_sides": row.get("perspectives_sides"),
        "perspectives_table": row.get("perspectives_table"),
        "followup_questions": row.get("followup_questions"),
        "location_context": row.get("location_context"),
        "more_from_briefing": more_from_briefing
    }
"""

if "def get_daily_briefing(" not in content:
    content += "\n" + new_endpoints

with open("app/main.py", "w") as f:
    f.write(content)

