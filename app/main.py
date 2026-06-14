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
    allow_origins=["*"],
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
        out_res = supabase.table("outlets").select("id, slug, government_alignment").execute()
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
            tier_dist[tier] += 1
            
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
