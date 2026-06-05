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


@app.get("/clusters")
def get_clusters(limit: int = 30, offset: int = 0):
    """Get story clusters ordered by outlet coverage."""
    result = supabase.table("clusters").select("*").order(
        "outlet_count", desc=True
    ).range(offset, offset + limit - 1).execute()
    return {"clusters": result.data, "count": len(result.data)}


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
