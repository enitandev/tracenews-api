"""Story lists: raw stories, landing, feed, category pages."""
import logging
from fastapi import APIRouter
from app.db import supabase
from app.image_utils import get_cluster_image, is_image_allowed
from app.tier_utils import get_outlet_tier, normalize_tier_distribution, count_outlet_tiers, card_distribution
from app.coverage import strip_embeddings, get_outlets_cache, enrich_clusters_with_live_tiers

logger = logging.getLogger(__name__)

router = APIRouter()

@router.get("/stories")
def get_stories(limit: int = 50, offset: int = 0):
    """Get latest stories."""
    result = supabase.table("stories").select("*").order(
        "published_at", desc=True
    ).range(offset, offset + limit - 1).execute()
    return {"stories": strip_embeddings(result.data), "count": len(result.data)}


@router.get("/stories/cluster/{cluster_id}")
def get_cluster_stories(cluster_id: str):
    """Get all stories in a cluster — the comparison view."""
    stories = supabase.table("stories").select("*").eq(
        "cluster_id", cluster_id
    ).order("published_at").execute()
    cluster = supabase.table("clusters").select("*").eq(
        "id", cluster_id
    ).single().execute()
    return {
        "cluster": strip_embeddings(cluster.data),
        "stories": strip_embeddings(stories.data),
        "outlet_count": len(stories.data),
    }


@router.get("/clusters/landing")
def get_landing_clusters(limit: int = 40):
    """Get optimized clusters for the landing page scrolling feed."""
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
        return outlet_count / (age_hours + 2)
        
    clusters.sort(key=relevance_score, reverse=True)
    clusters = clusters[:limit]
    
    # Format for frontend
    formatted = []
    for c in clusters:
        # Get first valid image
        image_url = get_cluster_image(c.get("stories"))
                
        formatted.append({
            "id": c["id"],
            "slug": c.get("slug"),
            "representative_title": c["representative_title"],
            "outlet_count": c["outlet_count"],
            "category": c.get("category", "General"),
            "coverage_stats": c.get("coverage_stats"),
            "monitoring_flags": c.get("monitoring_flags") or [],
            "image_url": image_url
        })
    enriched_clusters = enrich_clusters_with_live_tiers(formatted)
    filtered = []
    for c in enriched_clusters:
        dist = c.get("coverage_stats", {}).get("coverage_tier_distribution", {})
        scored = dist.get("govt_aligned", 0) + dist.get("mainstream", 0) + dist.get("watchdog", 0)
        if scored >= 2:
            filtered.append(c)
            
    return {"clusters": filtered, "count": len(filtered)}


@router.get("/clusters/feed")
def get_feed_clusters(limit: int = 30, offset: int = 0, tier: str = None):
    """Get full clusters with scores for the main feed."""
    query = supabase.table("clusters").select(
        "*, cluster_scores(*), stories(image_url)"
    ).gte("outlet_count", 2).order("first_seen_at", desc=True).limit(200)
    
    # If tier is requested, we can't filter at the SQL level easily because coverage_stats is JSON.
    # We will filter in Python below.
    result = query.execute()
    
    clusters = result.data or []
    from datetime import datetime, timezone, timedelta
    
    def relevance_score(cluster):
        now = datetime.now(timezone.utc)
        first_seen_str = cluster.get('first_seen_at')
        if not first_seen_str: return 0
        first_seen = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
        age_hours = (now - first_seen).total_seconds() / 3600
        outlet_count = cluster.get('outlet_count', 1)
        return outlet_count / (age_hours + 2)
        
    clusters.sort(key=relevance_score, reverse=True)
    
    enriched_clusters = enrich_clusters_with_live_tiers(clusters)
    
    floor_filtered = []
    for c in enriched_clusters:
        dist = c.get("coverage_stats", {}).get("coverage_tier_distribution", {})
        scored = dist.get("govt_aligned", 0) + dist.get("mainstream", 0) + dist.get("watchdog", 0)
        if scored >= 2:
            floor_filtered.append(c)
    enriched_clusters = floor_filtered
    if tier:
        filtered_clusters = []
        for c in enriched_clusters:
            dist = c.get("coverage_stats", {}).get("coverage_tier_distribution", {})
            # Find the loud tier
            loud_tier = "unscored"
            max_count = 0
            for t, count in dist.items():
                if t != "blog" and count > max_count:
                    max_count = count
                    loud_tier = t
            
            # Map API query to the internal tier name
            tier_mapping = {
                "govt": "govt_aligned",
                "mainstream": "mainstream",
                "watchdog": "watchdog"
            }
            if loud_tier == tier_mapping.get(tier, tier):
                filtered_clusters.append(c)
        enriched_clusters = filtered_clusters

    paginated = enriched_clusters[offset:offset + limit]
    
    formatted = []
    for c in paginated:
        image_url = get_cluster_image(c.get("stories"))
        
        c_dict = dict(c)
        c_dict["image_url"] = image_url
        formatted.append(c_dict)
    
    return {"clusters": strip_embeddings(formatted), "count": len(enriched_clusters)}

@router.get("/clusters/most-carried")
def get_most_carried_clusters(category: str, limit: int = 6):
    """Get the clusters with the highest distinct scored outlet coverage."""
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    thirty_days_str = (now - timedelta(days=30)).isoformat()
    
    # 1. Broad pre-filter: candidates from the last 30 days with outlet_count >= 8
    query = supabase.table("clusters").select(
        "id, slug, representative_title, category, coverage_stats, first_seen_at"
    ).eq("category", category).gte("first_seen_at", thirty_days_str).gte("outlet_count", 8).order("outlet_count", desc=True).limit(100)
    
    result = query.execute()
    candidate_clusters = result.data or []
    
    print(f"[DIAGNOSTICS] Category: {category}")
    print(f"[DIAGNOSTICS] Stage A - Candidate clusters pre-filter: {len(candidate_clusters)}")
    
    if not candidate_clusters:
        return {"clusters": [], "count": 0}

    cluster_ids = [c["id"] for c in candidate_clusters]
    
    # 2. Batch fetch distinct outlets via join
    cluster_stories = {}
    batch_size = 50
    total_rows = 0
    for i in range(0, len(cluster_ids), batch_size):
        batch_ids = cluster_ids[i:i + batch_size]
        res = supabase.table("stories").select("cluster_id, outlets!inner(slug, government_alignment, is_blog)").in_("cluster_id", batch_ids).execute()
        if res.data:
            total_rows += len(res.data)
            for s in res.data:
                cid = s.get("cluster_id")
                if cid not in cluster_stories:
                    cluster_stories[cid] = []
                cluster_stories[cid].append(s)
                
    print(f"[DIAGNOSTICS] Stage B - Rows returned by join: {total_rows}")

    # 3. Calculate true distinct counts and filter
    scored_clusters = []
    total_computed = 0
    for c in candidate_clusters:
        cid = c["id"]
        stories = cluster_stories.get(cid, [])
        total_computed += 1
        
        story_outlets = [s["outlets"] for s in stories if s.get("outlets")]
        unique_slugs = {o.get("slug") for o in story_outlets if o.get("slug")}
        tier_counts = count_outlet_tiers(story_outlets)
        tier_dist = card_distribution(tier_counts)
        scored = sum(tier_dist.values())
        
        if scored >= 8:
            stats = c.get("coverage_stats") or {}
            stats["coverage_tier_distribution"] = tier_dist
            stats["total_coverage"] = scored
            stats["blog_count"] = tier_counts["blog"]
            c["coverage_stats"] = stats
            c["scored_count"] = scored
            c["outlet_count"] = len(unique_slugs)
            scored_clusters.append(c)
            
    print(f"[DIAGNOSTICS] Stage C - Clusters computed: {total_computed}")
    print(f"[DIAGNOSTICS] Stage D - Clusters surviving floor (>= 8): {len(scored_clusters)}")
            
    # Sort by the derived scored count descending, then by age
    scored_clusters.sort(key=lambda x: (x.get("scored_count", 0), x.get("first_seen_at", "")), reverse=True)
    
    top_clusters = scored_clusters[:limit]
    
    return {"clusters": top_clusters, "count": len(top_clusters)}

@router.get("/clusters/by-category")
def get_clusters_by_category(category: str, limit: int = 8):
    """Get the most recent clusters for a category without an outlet floor (for COMPACT)."""
    # 1. Fetch exactly `limit` clusters
    query = supabase.table("clusters").select(
        "id, slug, representative_title, category, coverage_stats, first_seen_at"
    ).eq("category", category).order("first_seen_at", desc=True).limit(limit)
    
    result = query.execute()
    clusters = result.data or []
    
    if not clusters:
        return {"clusters": [], "count": 0}

    cluster_ids = [c["id"] for c in clusters]
    
    # 2. Batch fetch distinct outlets via join
    cluster_stories = {}
    batch_size = 50
    for i in range(0, len(cluster_ids), batch_size):
        batch_ids = cluster_ids[i:i + batch_size]
        res = supabase.table("stories").select("cluster_id, outlets!inner(slug, government_alignment, is_blog)").in_("cluster_id", batch_ids).execute()
        if res.data:
            for s in res.data:
                cid = s.get("cluster_id")
                if cid not in cluster_stories:
                    cluster_stories[cid] = []
                cluster_stories[cid].append(s)

    # 3. Calculate true distinct counts (no floor filtering)
    for c in clusters:
        cid = c["id"]
        stories = cluster_stories.get(cid, [])
        
        story_outlets = [s["outlets"] for s in stories if s.get("outlets")]
        unique_slugs = {o.get("slug") for o in story_outlets if o.get("slug")}
        tier_counts = count_outlet_tiers(story_outlets)
        tier_dist = card_distribution(tier_counts)
        scored = sum(tier_dist.values())
        
        stats = c.get("coverage_stats") or {}
        stats["coverage_tier_distribution"] = tier_dist
        stats["total_coverage"] = scored
        stats["blog_count"] = tier_counts["blog"]
        c["coverage_stats"] = stats
        c["scored_count"] = scored
        c["outlet_count"] = len(unique_slugs)
            
    return {"clusters": clusters, "count": len(clusters)}


@router.get("/categories/{category}/feed")
def get_category_feed(category: str, limit: int = 30, offset: int = 0):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    thirty_days_str = (now - timedelta(days=30)).isoformat()
    
    # Total count
    count_res = supabase.table("clusters").select("id", count="exact").eq("category", category).execute()
    total_cluster_count = count_res.count or 0
    
    # PHASE 1 - Lightweight metadata query
    clusters_res = supabase.table("clusters").select(
        "id, slug, representative_title, outlet_count, category, coverage_stats, first_seen_at"
    ).eq("category", category).gte("first_seen_at", thirty_days_str).order("first_seen_at", desc=True).limit(1000).execute()
    
    clusters = clusters_res.data or []
    
    # Compute bias breakdown
    bias_breakdown = { "govt_aligned": 0, "mainstream": 0, "watchdog": 0, "total": 0 }
    for c in clusters:
        stats = c.get("coverage_stats") or {}
        dist = normalize_tier_distribution(stats.get("coverage_tier_distribution"))
        if dist is None:
            continue
        for t in ("govt_aligned", "mainstream", "watchdog"):
            bias_breakdown[t] += dist[t]
        bias_breakdown["total"] += sum(dist.values())
        
    # Relevance sort
    def relevance_score(cluster):
        first_seen_str = cluster.get('first_seen_at')
        if not first_seen_str: return 0
        first_seen = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
        age_hours = (now - first_seen).total_seconds() / 3600
        return cluster.get('outlet_count', 1) / (age_hours + 2)
    clusters.sort(key=relevance_score, reverse=True)
    
    # The one-tier "monitoring spirit" pick (any tier >= 80%, no significance,
    # persistence or sourcing rails) is not selected any more: it was never
    # rendered, but it removed those stories from the page's lists. The key
    # stays in the response, empty, for compatibility.
    ms_candidates = []
    ms_ids = set()

    # Top stories candidates (fetch a few extra since we'll filter for images)
    candidates_by_outlet = sorted([c for c in clusters if c["id"] not in ms_ids], key=lambda x: x.get("outlet_count", 0), reverse=True)
    top_candidates = candidates_by_outlet[:6]
    top_ids = {c["id"] for c in top_candidates}
    
    # Paginated remaining
    remaining = [c for c in clusters if c["id"] not in ms_ids and c["id"] not in top_ids]
    paginated_remaining = remaining[offset:offset+limit]
    paginated_ids = {c["id"] for c in paginated_remaining}
    
    # PHASE 2 - Stories fetch for the ~35 target clusters
    target_ids = list(ms_ids | top_ids | paginated_ids)
    if target_ids:
        stories_res = supabase.table("stories").select(
            "cluster_id, image_url, outlets(slug, name, logo_url, government_alignment, independence_score, is_blog)"
        ).in_("cluster_id", target_ids).execute()
        stories_data = stories_res.data or []
        
        images_by_cluster = {}
        for s in stories_data:
            cid = s.get("cluster_id")
            if cid not in images_by_cluster and s.get("image_url"):
                if is_image_allowed(s["image_url"]):
                    images_by_cluster[cid] = s["image_url"]
                
        # Attach images
        for c in ms_candidates + top_candidates + paginated_remaining:
            c["image_url"] = images_by_cluster.get(c["id"])
            
    final_top_stories = [c for c in top_candidates if c.get("image_url")][:3]
    
    # Compute covered_most_by via RPC
    outlets_map, behavioral_map = get_outlets_cache()
    outlets_by_slug = {
        o.get('slug'): o 
        for o in outlets_map.values() 
        if o.get('slug')
    }
    
    covered_most_by = []
    
    try:
        rpc_res = supabase.rpc("get_category_top_outlets", {"p_category": category, "p_days": 30}).execute()
        top_outlets_data = rpc_res.data or []
        for row in top_outlets_data:
            slug = row["outlet_slug"]
            out = outlets_by_slug.get(slug)
            if not out: continue
            behav = behavioral_map.get(slug)
            
            tier = get_outlet_tier(out.get("government_alignment"), out.get("is_blog"))
                
            covered_most_by.append({"name": out.get("name"), "logo_url": out.get("logo_url"), "tier": tier})
    except Exception as e:
        import logging
        logging.error(f"Error calling get_category_top_outlets RPC: {e}")

    return {
        "category": category,
        "total_cluster_count": total_cluster_count,
        "top_stories": final_top_stories,
        "monitoring_spirit": ms_candidates,
        "stories": paginated_remaining,
        "covered_most_by": covered_most_by,
        "bias_breakdown": bias_breakdown
    }
