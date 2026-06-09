import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.scheduler import start_scheduler, stop_scheduler
from app.fetcher import run_fetch
from app.clusterer import run_clustering
from app.db import supabase
from app.framer import generate_framing_summary

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
        import traceback
        trace = traceback.format_exc()
        logger.error(f"Fetch failed with unhandled exception:\n{trace}")
        return {"status": "error", "message": str(e), "traceback": trace}


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


@app.get("/clusters/landing")
def get_landing_clusters(limit: int = 40):
    """Get optimized clusters for the landing page scrolling feed."""
    result = supabase.table("clusters").select(
        "id, representative_title, outlet_count, category, coverage_stats, monitoring_flags, stories(image_url)"
    ).gte("outlet_count", 2).order("first_seen_at", desc=True).limit(limit).execute()
    
    # Format for frontend
    formatted = []
    for c in result.data:
        # Get first valid image
        image_url = None
        for s in (c.get("stories") or []):
            if s.get("image_url"):
                image_url = s["image_url"]
                break
                
        formatted.append({
            "id": c["id"],
            "representative_title": c["representative_title"],
            "outlet_count": c["outlet_count"],
            "category": c.get("category", "General"),
            "coverage_stats": c.get("coverage_stats"),
            "monitoring_flags": c.get("monitoring_flags") or [],
            "image_url": image_url
        })
    return {"clusters": formatted, "count": len(formatted)}


@app.get("/clusters/feed")
def get_feed_clusters(limit: int = 30, offset: int = 0):
    """Get full clusters with scores for the main feed."""
    result = supabase.table("clusters").select(
        "*, cluster_scores(*)"
    ).gte("outlet_count", 2).order("first_seen_at", desc=True).range(offset, offset + limit - 1).execute()
    return {"clusters": result.data, "count": len(result.data)}


@app.get("/clusters/{id}/deep-dive")
def get_cluster_deep_dive(id: str):
    """Get full detailed analytics for a cluster and its stories."""
    cluster_res = supabase.table("clusters").select("*, cluster_scores(*)").eq("id", id).single().execute()
    cluster = cluster_res.data
    
    stories_res = supabase.table("stories").select(
        "*, story_bias_tags(bias_category_id, source), outlets(slug, government_alignment, independence_score, credibility_tier)"
    ).eq("cluster_id", id).order("published_at", desc=False).execute()
    
    stories = stories_res.data or []
    
    # Fetch behavioral scores
    slugs = list(set(s["outlets"]["slug"] for s in stories if s.get("outlets") and s["outlets"].get("slug")))
    behavioral_map = {}
    if slugs:
        behav_res = supabase.table("outlet_behavioral_scores").select("*").in_("outlet_slug", slugs).execute()
        behavioral_map = {b["outlet_slug"]: b for b in (behav_res.data or [])}
    
    # Flatten the outlet metadata directly onto the story object
    for s in stories:
        if s.get("outlets"):
            out = s["outlets"]
            slug = out.get("slug")
            s["outlet_alignment"] = out.get("government_alignment")
            s["outlet_independence"] = out.get("independence_score")
            s["outlet_tier"] = out.get("credibility_tier")
            
            behav = behavioral_map.get(slug) if slug else None
            tier = "unscored"
            if behav and behav.get("independence_score") is not None:
                if behav.get("brown_envelope_suspected"):
                    tier = "captured"
                else:
                    score = behav.get("independence_score")
                    if score >= 70: tier = "independent"
                    elif score >= 35: tier = "deferential"
                    else: tier = "captured"
            else:
                g_align = out.get("government_alignment")
                if g_align == "pro_government": tier = "captured"
                elif g_align == "opposition": tier = "independent"
                elif g_align == "neutral": tier = "deferential"
                
            s["outlet_coverage_tier"] = tier
            del s["outlets"]

    if stories:
        stories[0]["broke_story_first"] = True
    
    return {
        "cluster": cluster,
        "stories": stories
    }

@app.get("/clusters/{id}/framing")
def get_cluster_framing(id: str, alignment: str):
    """Generate an on-demand AI framing summary for a specific alignment."""
    # Map external requested alignment to internal tiers
    tier_map = {
        "government": "captured",
        "balanced": "deferential",
        "opposition": "independent"
    }
    target_tier = tier_map.get(alignment)
    if not target_tier:
        return {"bullets": []}

    stories_res = supabase.table("stories").select(
        "title, summary, outlets(slug, government_alignment, independence_score, credibility_tier)"
    ).eq("cluster_id", id).execute()
    
    stories = stories_res.data or []
    if not stories:
        return {"bullets": []}

    # Fetch behavioral scores
    slugs = list(set(s["outlets"]["slug"] for s in stories if s.get("outlets") and s["outlets"].get("slug")))
    behavioral_map = {}
    if slugs:
        behav_res = supabase.table("outlet_behavioral_scores").select("*").in_("outlet_slug", slugs).execute()
        behavioral_map = {b["outlet_slug"]: b for b in (behav_res.data or [])}

    filtered_stories = []
    for s in stories:
        if s.get("outlets"):
            out = s["outlets"]
            slug = out.get("slug")
            behav = behavioral_map.get(slug) if slug else None
            tier = "unscored"
            if behav and behav.get("independence_score") is not None:
                if behav.get("brown_envelope_suspected"):
                    tier = "captured"
                else:
                    score = behav.get("independence_score")
                    if score >= 70: tier = "independent"
                    elif score >= 35: tier = "deferential"
                    else: tier = "captured"
            else:
                g_align = out.get("government_alignment")
                if g_align == "pro_government": tier = "captured"
                elif g_align == "opposition": tier = "independent"
                elif g_align == "neutral": tier = "deferential"
            
            if tier == target_tier:
                filtered_stories.append(s)

    if not filtered_stories:
        return {"bullets": []}

    summary_json = generate_framing_summary(filtered_stories, alignment)
    return summary_json

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
