import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import traceback
from app.scheduler import start_scheduler, stop_scheduler
from app.fetcher import run_fetch
from app.clusterer import run_clustering
from app.db import supabase
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="TraceNews API",
    description="Nigerian media intelligence backend — Monitoring Spirit",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://tracenews.ng",
        "https://www.tracenews.ng",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── HEALTH ──────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "ok", "service": "tracenews-api"}


@app.get("/health")
def health():
    return {"status": "healthy"}


# ── MANUAL TRIGGERS ─────────────────────────────────

@app.post("/admin/fetch")
def trigger_fetch():
    """Manually trigger an RSS fetch run."""
    try:
        result = run_fetch()
        return {"status": "ok", **result}
    except Exception as e:
        logger.error(f"[trigger_fetch] manual fetch failed: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


@app.post("/admin/cluster")
def trigger_cluster():
    """Manually trigger a clustering run."""
    result = run_clustering()
    return {"status": "ok", **result}


@app.post("/admin/run")
def trigger_full_run():
    """Manually trigger fetch + cluster."""
    fetch = run_fetch()
    cluster = run_clustering()
    return {"status": "ok", "fetch": fetch, "cluster": cluster}


from fastapi import BackgroundTasks
from app.clusterer import run_full_recluster

@app.post("/admin/recluster-all")
async def recluster_all(background_tasks: BackgroundTasks):
    """One-time recovery endpoint to recluster all stories in the background."""
    background_tasks.add_task(run_full_recluster)
    return {"status": "started", "message": "Full recluster running in background. Check Railway logs."}


# ── STORIES API ─────────────────────────────────────

@app.get("/stories")
def get_stories(limit: int = 50, offset: int = 0):
    """Get latest stories."""
    result = supabase.table("stories").select("*").order(
        "published_at", desc=True
    ).range(offset, offset + limit - 1).execute()
    return {"stories": result.data, "count": len(result.data)}


@app.get("/stories/cluster/{cluster_id}")
def get_cluster_stories(cluster_id: str):
    """Get all stories in a cluster — the comparison view."""
    stories = supabase.table("stories").select("*").eq(
        "cluster_id", cluster_id
    ).order("published_at").execute()
    cluster = supabase.table("clusters").select("*").eq(
        "id", cluster_id
    ).single().execute()
    return {
        "cluster": cluster.data,
        "stories": stories.data,
        "outlet_count": len(stories.data),
    }

import time

_OUTLETS_CACHE = {}
_BEHAVIORAL_CACHE = {}
_LAST_CACHE_UPDATE = 0
CACHE_TTL = 3600  # 1 hour

def get_outlets_cache():
    global _OUTLETS_CACHE, _BEHAVIORAL_CACHE, _LAST_CACHE_UPDATE
    now = time.time()
    if now - _LAST_CACHE_UPDATE > CACHE_TTL or not _OUTLETS_CACHE:
        out_res = supabase.table("outlets").select("id, slug, government_alignment, name, logo_url, credibility_tier, headquarters_city, geopolitical_lean").execute()
        _OUTLETS_CACHE = {o["id"]: o for o in (out_res.data or [])}
        
        behav_res = supabase.table("outlet_behavioral_scores").select("*").execute()
        _BEHAVIORAL_CACHE = {b["outlet_slug"]: b for b in (behav_res.data or [])}
        
        _LAST_CACHE_UPDATE = now
    return _OUTLETS_CACHE, _BEHAVIORAL_CACHE

def compute_live_coverage_tier_distribution(cluster_id, stories, outlets_map, behavioral_map):
    tier_dist = {"pro_establishment": 0, "institutional": 0, "adversarial": 0, "unscored": 0}
    
    unique_outlet_ids = set()
    for s in stories:
        oid = s.get("outlet_id")
        if oid:
            unique_outlet_ids.add(oid)
            
    for oid in unique_outlet_ids:
        if oid not in outlets_map:
            continue
            
        out = outlets_map[oid]
        slug = out.get("slug")
        behav = behavioral_map.get(slug) if slug else None
        
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
            if g_align == "pro_government":
                tier = "pro_establishment"
            elif g_align == "opposition":
                tier = "adversarial"
            elif g_align == "neutral":
                tier = "institutional"
                
        if tier != "unscored":
            tier_dist[tier if tier in tier_dist else "unscored"] += 1
            
    return tier_dist

def enrich_clusters_with_live_tiers(clusters):
    if not clusters: return clusters
    
    outlets_map, behavioral_map = get_outlets_cache()
    cluster_ids = [c["id"] for c in clusters]
    
    stories_res = supabase.table("stories").select("id, cluster_id, outlet_id").in_("cluster_id", cluster_ids).execute()
    stories = stories_res.data or []
    
    stories_by_cluster = {}
    for s in stories:
        cid = s.get("cluster_id")
        if cid not in stories_by_cluster:
            stories_by_cluster[cid] = []
        stories_by_cluster[cid].append(s)
        
    for c in clusters:
        cid = c["id"]
        c_stories = stories_by_cluster.get(cid, [])
        live_dist = compute_live_coverage_tier_distribution(cid, c_stories, outlets_map, behavioral_map)
        
        blog_count = live_dist.pop("blog", 0)
        
        if not c.get("coverage_stats"):
            c["coverage_stats"] = {}
        c["coverage_stats"]["coverage_tier_distribution"] = live_dist
        c["coverage_stats"]["total_coverage"] = sum(live_dist.values())
        c["coverage_stats"]["blog_count"] = blog_count
        
    return clusters


@app.get("/clusters/landing")
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
        image_url = None
        for s in (c.get("stories") or []):
            if s.get("image_url"):
                image_url = s["image_url"]
                break
                
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
    return {"clusters": enrich_clusters_with_live_tiers(formatted), "count": len(formatted)}


@app.get("/clusters/feed")
def get_feed_clusters(limit: int = 30, offset: int = 0):
    """Get full clusters with scores for the main feed."""
    result = supabase.table("clusters").select(
        "*, cluster_scores(*), stories(image_url)"
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
    paginated = clusters[offset:offset + limit]
    
    formatted = []
    for c in paginated:
        image_url = None
        for s in (c.get("stories") or []):
            if s.get("image_url"):
                image_url = s["image_url"]
                break
        
        c_dict = dict(c)
        c_dict["image_url"] = image_url
        formatted.append(c_dict)
    
    return {"clusters": enrich_clusters_with_live_tiers(formatted), "count": len(clusters)}

@app.get("/clusters/by-slug/{slug}")
def get_cluster_by_slug(slug: str):
    """Get full detailed analytics for a cluster and its stories by slug."""
    cluster_res = supabase.table("clusters").select("*, cluster_scores(*)").eq("slug", slug).execute()
    
    if not cluster_res.data:
        return {"error": "Cluster not found"}
        
    cluster = cluster_res.data[0]
        
    stories_res = supabase.table("stories").select(
        "*, story_bias_tags(bias_category_id, source), outlets(slug, name, government_alignment, independence_score, credibility_tier, logo_url, ownership_name, ownership_type, ownership_transparency, party_proximity, track_record_status, brown_envelope_count, headquarters_city, geopolitical_lean)"
    ).eq("cluster_id", cluster["id"]).order("published_at", desc=False).execute()
    
    stories = stories_res.data or []
    
    outlets_map, behavioral_map = get_outlets_cache()
    
    cluster["coverage_stats"] = cluster.get("coverage_stats") or {}
    live_dist = compute_live_coverage_tier_distribution(
        cluster["id"], 
        stories, 
        outlets_map, 
        behavioral_map
    )
    blog_count = live_dist.pop("blog", 0)
    
    cluster["coverage_stats"]["coverage_tier_distribution"] = live_dist
    cluster["coverage_stats"]["total_coverage"] = sum(live_dist.values())
    cluster["coverage_stats"]["blog_count"] = blog_count
    
    # Flatten the outlet metadata directly onto the story object
    for s in stories:
        if s.get("outlets"):
            out = s["outlets"]
            s["outlet_alignment"] = out.get("government_alignment")
            s["outlet_independence"] = out.get("independence_score")
            s["outlet_tier"] = out.get("credibility_tier")
            s["outlet_logo_url"] = out.get("logo_url")
            if out.get("name"):
                s["outlet_name"] = out.get("name")
            
            behav = behavioral_map.get(out.get("slug"))
            if out.get("credibility_tier") == "blog":
                s["outlet_coverage_tier"] = "blog"
            elif behav and behav.get("independence_score") is not None:
                score = behav.get("independence_score")
                if behav.get("brown_envelope_suspected") or score < 35:
                    s["outlet_coverage_tier"] = "pro_establishment"
                elif score < 60:
                    s["outlet_coverage_tier"] = "institutional"
                else:
                    s["outlet_coverage_tier"] = "adversarial"
            else:
                g_align = out.get("government_alignment")
                if g_align == "pro_government":
                    s["outlet_coverage_tier"] = "pro_establishment"
                elif g_align == "opposition":
                    s["outlet_coverage_tier"] = "adversarial"
                elif g_align == "neutral":
                    s["outlet_coverage_tier"] = "institutional"
                else:
                    s["outlet_coverage_tier"] = "unscored"

    return {"cluster": cluster, "stories": stories}



@app.get("/clusters/{id}/deep-dive")
def get_cluster_deep_dive(id: str):
    """Get full detailed analytics for a cluster and its stories."""
    cluster_res = supabase.table("clusters").select("*, cluster_scores(*)").eq("id", id).single().execute()
    cluster = cluster_res.data
    
    stories_res = supabase.table("stories").select(
        "*, story_bias_tags(bias_category_id, source), outlets(slug, name, government_alignment, independence_score, credibility_tier, logo_url, ownership_name, ownership_type, ownership_transparency, party_proximity, track_record_status, brown_envelope_count, headquarters_city, geopolitical_lean)"
    ).eq("cluster_id", id).order("published_at", desc=False).execute()
    
    stories = stories_res.data or []
    
    outlets_map, behavioral_map = get_outlets_cache()
    
    cluster["coverage_stats"] = cluster.get("coverage_stats") or {}
    live_dist = compute_live_coverage_tier_distribution(
        cluster["id"], 
        stories, 
        outlets_map, 
        behavioral_map
    )
    blog_count = live_dist.pop("blog", 0)
    
    cluster["coverage_stats"]["coverage_tier_distribution"] = live_dist
    cluster["coverage_stats"]["total_coverage"] = sum(live_dist.values())
    cluster["coverage_stats"]["blog_count"] = blog_count
    
    # Flatten the outlet metadata directly onto the story object
    for s in stories:
        if s.get("outlets"):
            out = s["outlets"]
            slug = out.get("slug")
            s["outlet_alignment"] = out.get("government_alignment")
            s["outlet_independence"] = out.get("independence_score")
            s["outlet_tier"] = out.get("credibility_tier")
            s["outlet_logo_url"] = out.get("logo_url")
            if out.get("name"):
                s["outlet_name"] = out.get("name")
            
            behav = behavioral_map.get(slug) if slug else None
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
                
            s["outlet_coverage_tier"] = tier
            
            # Carry forward all required outlet fields before deleting
            s["outlets_full"] = out
            del s["outlets"]

    if stories:
        stories[0]["broke_story_first"] = True
    
    return {
        "cluster": cluster,
        "stories": stories
    }

@app.get("/story-og/{slug}")
async def story_og(slug: str):
    from fastapi.responses import HTMLResponse
    import re
    
    cluster_res = supabase.table("clusters")\
      .select("id, representative_title")\
      .eq("slug", slug).execute()
    
    if not cluster_res.data:
      return HTMLResponse(
        content="<html><head>"\
        "<meta http-equiv='refresh' "\
        "content='0;url=https://"\
        "tracenews.ng'/></head></html>"
      )
    
    cluster = cluster_res.data[0]
    cluster_id = cluster["id"]
    title = cluster["representative_title"]
    canonical = f"https://tracenews.ng/story/{slug}"
    
    story_res = supabase.table("stories")\
      .select("image_url, summary")\
      .eq("cluster_id", cluster_id)\
      .not_.is_("image_url", "null")\
      .limit(1).execute()
    
    image_url = "https://tracenews.ng/og-default.png"
    description = "See every side of every Nigerian news story on TraceNews."
    
    if story_res.data:
      image_url = story_res.data[0].get("image_url") or image_url
      raw = story_res.data[0].get("summary") or ""
      clean = re.sub(r'<[^>]+>', '', raw).strip()[:160]
      if clean:
        description = clean
    
    # Escape quotes in title/description for HTML safety
    safe_title = title.replace('"', '&quot;')
    safe_desc = description.replace('"', '&quot;')
    
    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{safe_title}</title>
  <meta property="og:type" content="article">
  <meta property="og:title" content="{safe_title}">
  <meta property="og:description" content="{safe_desc}">
  <meta property="og:image" content="{image_url}">
  <meta property="og:url" content="{canonical}">
  <meta property="og:site_name" content="TraceNews">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{safe_title}">
  <meta name="twitter:description" content="{safe_desc}">
  <meta name="twitter:image" content="{image_url}">
  <meta http-equiv="refresh" content="0;url={canonical}">
</head>
<body>
  <a href="{canonical}">{safe_title}</a>
</body>
</html>"""
    
    return HTMLResponse(content=html)

@app.get("/clusters/{id}/framing")
def get_cluster_framing(id: str, alignment: str):
    """Fetch cached AI framing summary for a specific alignment."""
    target_tier = alignment
    if target_tier not in ["pro_establishment", "institutional", "adversarial", "all", "comparison"]:
        return {"bullets": []}

    cluster_res = supabase.table("clusters").select("framing_cache").eq("id", id).execute()
    cluster_data = cluster_res.data[0] if cluster_res.data else {}
    framing_cache = cluster_data.get("framing_cache") or {}

    from app.framer import generate_single_cluster_framing
    
    needs_regen = False
    if target_tier not in framing_cache:
        needs_regen = True
    else:
        bullets = framing_cache[target_tier]
        if not bullets or len(bullets) == 0:
            needs_regen = True
        elif any("insufficient" in str(b).lower() for b in bullets):
            needs_regen = True
            
    if needs_regen:
        try:
            new_framing = generate_single_cluster_framing(id)
            if new_framing:
                framing_cache = new_framing
        except Exception as e:
            logger.error(f"[get_cluster_framing] regen failed for {id}: {type(e).__name__}: {e}")
            logger.error(traceback.format_exc())

    if target_tier in framing_cache:
        bullets = framing_cache[target_tier]
        if bullets and len(bullets) > 0 and not any("insufficient" in str(b).lower() for b in bullets):
            return {"bullets": bullets, "cached": True}
        
    return {"bullets": [], "cached": False}


class FeedbackRequest(BaseModel):
    cluster_id: str
    tier: str
    comment: str

@app.post("/framing/feedback")
def submit_framing_feedback(req: FeedbackRequest):
    """Submit user feedback for AI framing."""
    supabase.table("framing_feedback").insert({
        "cluster_id": req.cluster_id,
        "tier": req.tier,
        "comment": req.comment
    }).execute()
    return {"status": "success"}


@app.get("/categories/{category}/feed")
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
    bias_breakdown = { "pro_establishment": 0, "institutional": 0, "adversarial": 0, "total": 0 }
    for c in clusters:
        stats = c.get("coverage_stats") or {}
        dist = stats.get("coverage_tier_distribution", {})
        bias_breakdown["pro_establishment"] += dist.get("pro_establishment", 0)
        bias_breakdown["institutional"] += dist.get("institutional", 0)
        bias_breakdown["adversarial"] += dist.get("adversarial", 0)
        bias_breakdown["total"] += sum(dist.values())
        
    # Relevance sort
    def relevance_score(cluster):
        first_seen_str = cluster.get('first_seen_at')
        if not first_seen_str: return 0
        first_seen = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
        age_hours = (now - first_seen).total_seconds() / 3600
        return cluster.get('outlet_count', 1) / (age_hours + 2)
    clusters.sort(key=relevance_score, reverse=True)
    
    # Monitoring spirit candidates
    monitoring_spirit = []
    for c in clusters:
        if c.get("outlet_count", 0) >= 3:
            stats = c.get("coverage_stats") or {}
            dist = stats.get("coverage_tier_distribution", {})
            total = sum(dist.values())
            if total > 0:
                for k, v in dist.items():
                    if v / total >= 0.8:
                        monitoring_spirit.append(c)
                        break
    monitoring_spirit.sort(key=lambda x: x.get("outlet_count", 0), reverse=True)
    ms_candidates = monitoring_spirit[:2]
    ms_ids = {c["id"] for c in ms_candidates}
    
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
            "cluster_id, image_url, outlets(slug, name, logo_url, government_alignment, independence_score, credibility_tier)"
        ).in_("cluster_id", target_ids).execute()
        stories_data = stories_res.data or []
        
        images_by_cluster = {}
        for s in stories_data:
            cid = s.get("cluster_id")
            if cid not in images_by_cluster and s.get("image_url"):
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
            
            tier = "unscored"
            if out.get("credibility_tier") == "blog": tier = "blog"
            elif behav and behav.get("independence_score") is not None:
                score = behav.get("independence_score")
                tier = "pro_establishment" if (behav.get("brown_envelope_suspected") or score < 35) else "institutional" if score < 60 else "adversarial"
            else:
                g_align = out.get("government_alignment")
                tier = "pro_establishment" if g_align == "pro_government" else "adversarial" if g_align == "opposition" else "institutional" if g_align == "neutral" else "unscored"
                
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

@app.get("/search")
def search_clusters(q: str, limit: int = 20):
    """Search clusters by keyword in representative_title."""
    res = supabase.table("clusters")\
        .select("id, slug, representative_title, outlet_count, category, coverage_stats, first_seen_at")\
        .ilike("representative_title", f"%{q}%")\
        .gte("outlet_count", 2)\
        .order("first_seen_at", desc=True)\
        .limit(limit)\
        .execute()
    return res.data

# ── OUTLETS API ─────────────────────────────────────

@app.get("/outlets")
def get_outlets():
    result = supabase.table("outlets").select("*").eq(
        "active", True
    ).order("name").execute()
    return {"outlets": result.data, "count": len(result.data)}


@app.get("/outlets/{slug}")
def get_outlet(slug: str):
    result = supabase.table("outlets").select("*").eq(
        "slug", slug
    ).single().execute()
    stories = supabase.table("stories").select("*").eq(
        "outlet_slug", slug
    ).order("published_at", desc=True).limit(20).execute()
    return {
        "outlet": result.data,
        "recent_stories": stories.data,
    }


@app.get("/daily-briefing")
def get_daily_briefing():
    from datetime import datetime, timezone, timedelta
    
    lagos_now = datetime.now(timezone.utc) + timedelta(hours=1)
    today = lagos_now.date().isoformat()
    
    rows_res = supabase.table("daily_briefings")\
        .select("id, date, cluster_id, cluster_slug, position, generation_status, perspectives_title, ground_summary")\
        .eq("date", today)\
        .eq("generation_status", "complete")\
        .order("position")\
        .execute()
    
    rows = rows_res.data or []
    
    if not rows:
        fallback_res = supabase.table(
            "daily_briefings"
        ).select(
            "id, date, cluster_id, cluster_slug, position, generation_status, perspectives_title, ground_summary"
        ).eq(
            "generation_status", "complete"
        ).order("date", desc=True)\
        .order("position")\
        .limit(9)\
        .execute()
        
        rows = fallback_res.data or []
        
        if not rows:
            return {
                "date": today,
                "status": "no_briefing",
                "stories": []
            }
    
    # Enrich each row with cluster data (image, outlet_count, category)
    cluster_ids = [r["cluster_id"] for r in rows]
    
    clusters_res = supabase.table("clusters")\
        .select("id, slug, representative_title, outlet_count, category, first_seen_at, coverage_stats, stories(image_url)")\
        .in_("id", cluster_ids)\
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
    row_res = supabase.table("daily_briefings")\
        .select("*")\
        .eq("cluster_slug", slug)\
        .eq("generation_status", "complete")\
        .order("date", desc=True)\
        .limit(1)\
        .execute()
    
    if not row_res.data:
        raise HTTPException(
            status_code=404,
            detail="Briefing not found for this story"
        )
    
    row = row_res.data[0]
    
    # Get full cluster data including stories with outlet info
    cluster_res = supabase.table("clusters")\
        .select("id, slug, representative_title, outlet_count, category, first_seen_at, coverage_stats")\
        .eq("id", row["cluster_id"])\
        .execute()
    
    cluster = cluster_res.data[0] if cluster_res.data else {}
    
    # Get stories with outlet data for Bias Distribution sidebar
    stories_res = supabase.table("stories")\
        .select("id, title, url, outlet_slug, published_at, image_url, outlets(slug, name, logo_url, independence_score, credibility_tier, government_alignment)")\
        .eq("cluster_id", row["cluster_id"])\
        .order("published_at")\
        .execute()
    
    stories = stories_res.data or []
    
    # Get first available image
    image_url = None
    for s in stories:
        if s.get("image_url"):
            image_url = s["image_url"]
            break
    
    # Get "More from Today's Briefing"
    other_rows_res = supabase.table("daily_briefings")\
        .select("position, cluster_slug, perspectives_title, ground_summary")\
        .eq("date", row["date"])\
        .eq("generation_status", "complete")\
        .neq("cluster_slug", slug)\
        .order("position")\
        .execute()
    
    other_rows = other_rows_res.data or []
    
    # Enrich other rows with cluster data
    if other_rows:
        other_cluster_slugs = [r["cluster_slug"] for r in other_rows]
        other_clusters_res = supabase.table("clusters")\
            .select("slug, representative_title, outlet_count, category, coverage_stats, stories(image_url)")\
            .in_("slug", other_cluster_slugs)\
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
