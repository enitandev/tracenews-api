import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    result = run_fetch()
    return {"status": "ok", **result}


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


@app.post("/admin/recluster-all")
def trigger_recluster_all():
    """One-time recovery endpoint to recluster all stories."""
    from app.clusterer import backfill_missing_embeddings
    from app.scorer import run_scoring
    
    # 1. Backfill embeddings
    backfill_missing_embeddings()
    
    # 2. Run full clustering
    cluster_res = run_clustering(all_time=True)
    
    # 3. Run scoring
    score_res = run_scoring(all_time=True)
    
    return {
        "status": "ok",
        "clustering": cluster_res,
        "scoring": score_res
    }


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
    # Note: In Supabase, joining via select("*, cluster_scores(*), stories(*)") works but fetching all stories is heavy.
    # To keep it light, we'll fetch clusters + scores and just the first image.
    result = supabase.table("clusters").select(
        "id, representative_title, outlet_count, cluster_scores(dominant_bias_slug, dominant_bias_color), stories(image_url)"
    ).gte("outlet_count", 2).order("first_seen_at", desc=True).limit(limit).execute()
    
    # Format for frontend
    formatted = []
    for c in result.data:
        scores = c.get("cluster_scores", {}) or {}
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
            "dominant_bias_slug": scores.get("dominant_bias_slug"),
            "dominant_bias_color": scores.get("dominant_bias_color"),
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
    
    stories_res = supabase.table("stories").select("*, story_bias_tags(bias_category_id, source)").eq("cluster_id", id).order("published_at", desc=False).execute()
    stories = stories_res.data or []
    
    if stories:
        stories[0]["broke_story_first"] = True
    
    return {
        "cluster": cluster,
        "stories": stories
    }

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
