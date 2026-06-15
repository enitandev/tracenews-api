import re

with open("app/main.py", "r") as f:
    content = f.read()

# 1. Update landing endpoint
landing_old = """@app.get("/clusters/landing")
def get_landing_clusters(limit: int = 40):
    \"\"\"Get optimized clusters for the landing page scrolling feed.\"\"\"
    result = supabase.table("clusters").select(
        "id, slug, representative_title, outlet_count, category, coverage_stats, monitoring_flags, stories(image_url)"
    ).gte("outlet_count", 2).order("first_seen_at", desc=True).limit(limit).execute()
    
    # Format for frontend
    formatted = []
    for c in result.data:"""

landing_new = """@app.get("/clusters/landing")
def get_landing_clusters(limit: int = 40):
    \"\"\"Get optimized clusters for the landing page scrolling feed.\"\"\"
    result = supabase.table("clusters").select(
        "id, slug, representative_title, outlet_count, category, coverage_stats, monitoring_flags, first_seen_at, stories(image_url)"
    ).gte("outlet_count", 2).order("first_seen_at", desc=True).limit(200).execute()
    
    clusters = result.data or []
    from datetime import datetime, timezone, timedelta
    
    def relevance_score(cluster):
        now = datetime.now(timezone.utc)
        first_seen_str = cluster.get('first_seen_at')
        if not first_seen_str: return 0
        first_seen = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
        age_hours = (now - first_seen).total_seconds() / 3600
        outlet_count = cluster.get('outlet_count', 1)
        if age_hours <= 6: return outlet_count * 3
        elif age_hours <= 24: return outlet_count * 2
        else: return outlet_count * 1
        
    clusters.sort(key=relevance_score, reverse=True)
    clusters = clusters[:limit]
    
    # Format for frontend
    formatted = []
    for c in clusters:"""

content = content.replace(landing_old, landing_new)

# 2. Update feed endpoint
feed_old = """@app.get("/clusters/feed")
def get_feed_clusters(limit: int = 30, offset: int = 0):
    \"\"\"Get full clusters with scores for the main feed.\"\"\"
    result = supabase.table("clusters").select(
        "*, cluster_scores(*)"
    ).gte("outlet_count", 2).order("first_seen_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"clusters": result.data, "count": len(result.data)}"""

feed_new = """@app.get("/clusters/feed")
def get_feed_clusters(limit: int = 30, offset: int = 0):
    \"\"\"Get full clusters with scores for the main feed.\"\"\"
    result = supabase.table("clusters").select(
        "*, cluster_scores(*)"
    ).gte("outlet_count", 2).order("first_seen_at", desc=True).limit(200).execute()
    
    clusters = result.data or []
    from datetime import datetime, timezone, timedelta
    
    def relevance_score(cluster):
        now = datetime.now(timezone.utc)
        first_seen_str = cluster.get('first_seen_at')
        if not first_seen_str: return 0
        first_seen = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
        age_hours = (now - first_seen).total_seconds() / 3600
        outlet_count = cluster.get('outlet_count', 1)
        if age_hours <= 6: return outlet_count * 3
        elif age_hours <= 24: return outlet_count * 2
        else: return outlet_count * 1
        
    clusters.sort(key=relevance_score, reverse=True)
    paginated = clusters[offset:offset + limit]
    
    return {"clusters": paginated, "count": len(clusters)}"""

content = content.replace(feed_old, feed_new)

# 3. Add search endpoint
search_endpoint = """
@app.get("/search")
def search_clusters(q: str, limit: int = 20):
    \"\"\"Search clusters by keyword in representative_title.\"\"\"
    res = supabase.table("clusters")\\
        .select("id, slug, representative_title, outlet_count, category, coverage_stats, first_seen_at")\\
        .ilike("representative_title", f"%{q}%")\\
        .gte("outlet_count", 2)\\
        .order("first_seen_at", desc=True)\\
        .limit(limit)\\
        .execute()
    return res.data
"""

if "/search" not in content:
    # Add it before GET /outlets
    content = content.replace("# ── OUTLETS API ─────────────────────────────────────", search_endpoint + "\n# ── OUTLETS API ─────────────────────────────────────")

with open("app/main.py", "w") as f:
    f.write(content)

