"""
FastAPI app setup: lifespan (scheduler), error handler, CORS and routers.
Endpoints live in app/routers/; shared coverage/verdict helpers in
app/coverage.py.
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.scheduler import start_scheduler, stop_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def warm_public_caches():
    """Build the homepage lists and the Briefing once at start, in the
    background, so the first reader after a deploy does not wait. The
    arguments match what the homepage requests, so the cached copies are the
    ones it reads. A failure is logged; the first request then builds it."""
    from app.routers import briefing, feeds
    jobs = [
        ("landing", lambda: feeds.get_landing_clusters(limit=15)),
        ("feed", lambda: feeds.get_feed_clusters(limit=65, offset=15, tier=None)),
        ("briefing", lambda: briefing.get_daily_briefing() if briefing.BRIEFING_PUBLIC else None),
    ] + [
        # The homepage's category rails (src/pages/Home.jsx section order).
        (f"most-carried {cat}", lambda cat=cat: feeds.get_most_carried_clusters(category=cat, limit=6))
        for cat in ("Politics", "Economy", "Sports", "Entertainment", "Security", "Health",
                    "Education", "International", "Technology", "Religion", "Judiciary", "General")
    ]
    for name, job in jobs:
        try:
            job()
        except Exception:
            logger.exception(f"[startup] warming the {name} cache failed")


@asynccontextmanager
async def lifespan(app: FastAPI):
    start_scheduler()
    import threading
    threading.Thread(target=warm_public_caches, daemon=True).start()
    yield
    stop_scheduler()


app = FastAPI(
    title="TraceNews API",
    description="Nigerian media intelligence backend — Monitoring Spirit",
    version="0.1.0",
    lifespan=lifespan,
)

ALLOWED_ORIGINS = [
    "https://tracenews.ng",
    "https://www.tracenews.ng",
    "http://localhost:5173",
]


SLOW_REQUEST_SECONDS = 2.0


@app.middleware("http")
async def time_requests(request: Request, call_next):
    """Every response carries its server time (Server-Timing, visible in the
    browser's network panel); requests slower than SLOW_REQUEST_SECONDS are
    logged with their path so slow screens can be found from the logs."""
    import time
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start
    response.headers["Server-Timing"] = f"app;dur={elapsed * 1000:.0f}"
    if elapsed >= SLOW_REQUEST_SECONDS:
        logger.warning(f"[slow] {request.method} {request.url.path} {elapsed:.1f}s status={response.status_code}")
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    # Full detail goes to the logs only; the client gets a generic 500.
    logger.exception(f"Unhandled exception on {request.method} {request.url.path}")
    headers = {}
    origin = request.headers.get("origin")
    # Error responses bypass the CORS middleware, so mirror its policy here:
    # allowed origins only, never an arbitrary caller with credentials.
    if origin in ALLOWED_ORIGINS:
        headers = {
            "Access-Control-Allow-Origin": origin,
            "Access-Control-Allow-Credentials": "true",
            "Vary": "Origin",
        }
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"}, headers=headers)

from app.withdrawn_fields import WithdrawnFieldsMiddleware

# Added before CORS so CORS stays the outermost layer.
app.add_middleware(WithdrawnFieldsMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.routers import corrections
from app.routers import monitoring_spirit_admin
from app.routers import politicians_admin
from app.routers import auth as auth_router
from app.routers import reader
from app.routers import admin_overview
from app.routers import system, feeds, story, seo, search, profiles, briefing


app.include_router(corrections.router)
app.include_router(monitoring_spirit_admin.router)
app.include_router(politicians_admin.router)
app.include_router(admin_overview.router)

app.include_router(auth_router.router)
app.include_router(reader.router)

app.include_router(system.router)
app.include_router(feeds.router)
app.include_router(story.router)
app.include_router(seo.router)
app.include_router(search.router)
app.include_router(profiles.router)
app.include_router(briefing.router)
