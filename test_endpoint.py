from datetime import datetime, timezone, timedelta

def build_endpoint_code():
    code = """
@app.get("/categories/{category}/feed")
def get_category_feed(category: str, limit: int = 30, offset: int = 0):
    from datetime import datetime, timezone, timedelta
    now = datetime.now(timezone.utc)
    thirty_days_ago = now - timedelta(days=30)
    thirty_days_str = thirty_days_ago.isoformat()
    
    count_res = supabase.table("clusters").select("id", count="exact").eq("category", category).execute()
    total_cluster_count = count_res.count or 0
    
    # Fetch clusters for the last 30 days
    # Since we need to compute aggregates, we get up to 1000 recent clusters
    clusters_res = supabase.table("clusters").select(
        "id, slug, representative_title, outlet_count, category, coverage_stats, monitoring_flags, first_seen_at, stories(id, published_at, created_at, image_url, outlets(slug, name, government_alignment, independence_score, credibility_tier, logo_url, ownership_name, ownership_type, ownership_transparency, party_proximity, track_record_status, brown_envelope_count, headquarters_city, geopolitical_lean))"
    ).eq("category", category).gte("first_seen_at", thirty_days_str).order("first_seen_at", desc=True).limit(1000).execute()
    
    clusters = clusters_res.data or []
    outlets_map, behavioral_map = get_outlets_cache()
    
    bias_breakdown = {
        "pro_establishment": 0,
        "institutional": 0,
        "adversarial": 0,
        "total": 0
    }
    outlet_counts = {}
    
    for c in clusters:
        c_stories = c.get("stories") or []
        live_dist = compute_live_coverage_tier_distribution(
            c["id"], c_stories, outlets_map, behavioral_map
        )
        c["coverage_stats"] = c.get("coverage_stats") or {}
        c["coverage_stats"]["coverage_tier_distribution"] = live_dist
        c["coverage_stats"]["total_coverage"] = sum(live_dist.values())
        c["coverage_stats"]["blog_count"] = live_dist.pop("blog", 0)
        
        bias_breakdown["pro_establishment"] += live_dist.get("pro_establishment", 0)
        bias_breakdown["institutional"] += live_dist.get("institutional", 0)
        bias_breakdown["adversarial"] += live_dist.get("adversarial", 0)
        bias_breakdown["total"] += sum(live_dist.values())
        
        c["image_url"] = None
        for s in c_stories:
            if s.get("image_url") and not c["image_url"]:
                c["image_url"] = s["image_url"]
            
            out = s.get("outlets")
            if out:
                slug = out.get("slug")
                if slug:
                    if slug not in outlet_counts:
                        outlet_counts[slug] = {"count": 0, "outlet": out}
                    outlet_counts[slug]["count"] += 1
                    
        # Remove stories array to save payload size, frontend only needs cluster info
        del c["stories"]

    sorted_outlets = sorted(outlet_counts.values(), key=lambda x: x["count"], reverse=True)[:5]
    covered_most_by = []
    for item in sorted_outlets:
        out = item["outlet"]
        behav = behavioral_map.get(out.get("slug"))
        tier = "unscored"
        if out.get("credibility_tier") == "blog":
            tier = "blog"
        elif behav and behav.get("independence_score") is not None:
            score = behav.get("independence_score")
            if behav.get("brown_envelope_suspected") or score < 35:
                tier = "pro_establishment"
            elif score < 60:
                tier = "institutional"
            else:
                tier = "adversarial"
        else:
            g_align = out.get("government_alignment")
            if g_align == "pro_government": tier = "pro_establishment"
            elif g_align == "opposition": tier = "adversarial"
            elif g_align == "neutral": tier = "institutional"
            
        covered_most_by.append({
            "name": out.get("name"),
            "logo_url": out.get("logo_url"),
            "tier": tier
        })
        
    monitoring_spirit = []
    for c in clusters:
        if c.get("outlet_count", 0) >= 3:
            dist = c["coverage_stats"].get("coverage_tier_distribution", {})
            total = sum(dist.values())
            if total > 0:
                for k, v in dist.items():
                    if v / total >= 0.8:
                        monitoring_spirit.append(c)
                        break
    monitoring_spirit.sort(key=lambda x: x.get("outlet_count", 0), reverse=True)
    monitoring_spirit = monitoring_spirit[:2]
    ms_ids = {c["id"] for c in monitoring_spirit}
    
    with_images = [c for c in clusters if c.get("image_url") and c["id"] not in ms_ids]
    with_images.sort(key=lambda x: x.get("outlet_count", 0), reverse=True)
    top_stories = with_images[:3]
    top_ids = {c["id"] for c in top_stories}
    
    remaining = [c for c in clusters if c["id"] not in top_ids and c["id"] not in ms_ids]
    def relevance_score(cluster):
        first_seen_str = cluster.get('first_seen_at')
        if not first_seen_str: return 0
        first_seen = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
        age_hours = (now - first_seen).total_seconds() / 3600
        outlet_count = cluster.get('outlet_count', 1)
        return outlet_count / (age_hours + 2)
    remaining.sort(key=relevance_score, reverse=True)
    paginated_remaining = remaining[offset:offset+limit]
    
    return {
        "category": category,
        "total_cluster_count": total_cluster_count,
        "top_stories": enrich_clusters_with_live_tiers(top_stories),
        "monitoring_spirit": enrich_clusters_with_live_tiers(monitoring_spirit),
        "stories": enrich_clusters_with_live_tiers(paginated_remaining),
        "covered_most_by": covered_most_by,
        "bias_breakdown": bias_breakdown
    }
"""
    return code
