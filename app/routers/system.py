"""Service meta and manual pipeline triggers."""
import logging
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from app.admin_auth import require_permission
from app.scheduler import scheduler_running
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
    return {"status": "healthy", "scheduler_running": scheduler_running()}


# ── MANUAL TRIGGERS ─────────────────────────────────
# These start paid pipeline work (embeddings) and run outside the worker's
# overlap lock, so they require a staff role with platform_health write access.
pipeline_admin = Depends(require_permission("platform_health", "edit"))

@router.post("/admin/fetch", dependencies=[pipeline_admin])
def trigger_fetch():
    """Manually trigger an RSS fetch run."""
    try:
        result = run_fetch()
        return {"status": "ok", **result}
    except Exception as e:
        logger.exception("[trigger_fetch] manual fetch failed")
        return {"status": "error", "message": f"{type(e).__name__}: {e}"}


@router.post("/admin/cluster", dependencies=[pipeline_admin])
def trigger_cluster():
    """Manually trigger a clustering run."""
    result = run_clustering()
    return {"status": "ok", **result}


@router.post("/admin/run", dependencies=[pipeline_admin])
def trigger_full_run():
    """Manually trigger fetch + cluster."""
    fetch = run_fetch()
    cluster = run_clustering()
    return {"status": "ok", "fetch": fetch, "cluster": cluster}


from app.clusterer import run_full_recluster, RECORD_HOLD

@router.post("/admin/recluster-all", dependencies=[pipeline_admin])
def recluster_all(background_tasks: BackgroundTasks):
    """One-time recovery endpoint to recluster all stories in the background."""
    if RECORD_HOLD:
        raise HTTPException(status_code=409, detail="Refused: a record hold is on and a full recluster would wipe every cluster.")
    background_tasks.add_task(run_full_recluster)
    return {"status": "started", "message": "Full recluster running in background. Check Railway logs."}


# ── STORIES API ─────────────────────────────────────
