"""
FastAPI app setup: lifespan (scheduler), error handler, CORS and routers.
Endpoints live in app/routers/; shared coverage/verdict helpers in
app/coverage.py.
"""
import logging
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.scheduler import start_scheduler, stop_scheduler

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

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Global exception: {type(exc).__name__}: {exc}")
    logger.error(traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal Server Error", "traceback": traceback.format_exc()},
        headers={
            "Access-Control-Allow-Origin": request.headers.get("origin", "*"),
            "Access-Control-Allow-Credentials": "true"
        }
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
app.include_router(admin_overview.router)

app.include_router(system.router)
app.include_router(feeds.router)
app.include_router(story.router)
app.include_router(seo.router)
app.include_router(search.router)
app.include_router(profiles.router)
app.include_router(briefing.router)
