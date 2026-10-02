"""Service meta and manual pipeline triggers."""
import logging
import traceback
from fastapi import APIRouter
from app.fetcher import run_fetch
from app.clusterer import run_clustering

logger = logging.getLogger(__name__)

router = APIRouter()

import os
@router.get("/version")
def get_version():
    """Returns the git commit SHA of the running process."""
    return {"sha": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "unknown")}

# ── HEALTH ──────────────────────────────────────────

@router.get("/")
def root():
    return {"status": "ok", "service": "tracenews-api"}


@router.get("/health")
def health():
    return {"status": "healthy"}


# ── MANUAL TRIGGERS ─────────────────────────────────

@router.post("/admin/fetch")
def trigger_fetch():
    """Manually trigger an RSS fetch run."""
    try:
        result = run_fetch()
        return {"status": "ok", **result}
    except Exception as e:
        logger.error(f"[trigger_fetch] manual fetch failed: {type(e).__name__}: {e}")
        logger.error(traceback.format_exc())
        return {"status": "error", "message": str(e), "traceback": traceback.format_exc()}


@router.post("/admin/cluster")
def trigger_cluster():
    """Manually trigger a clustering run."""
    result = run_clustering()
    return {"status": "ok", **result}


@router.post("/admin/run")
def trigger_full_run():
    """Manually trigger fetch + cluster."""
    fetch = run_fetch()
    cluster = run_clustering()
    return {"status": "ok", "fetch": fetch, "cluster": cluster}


from fastapi import BackgroundTasks
from app.clusterer import run_full_recluster

@router.post("/admin/recluster-all")
async def recluster_all(background_tasks: BackgroundTasks):
    """One-time recovery endpoint to recluster all stories in the background."""
    background_tasks.add_task(run_full_recluster)
    return {"status": "started", "message": "Full recluster running in background. Check Railway logs."}


# ── STORIES API ─────────────────────────────────────
