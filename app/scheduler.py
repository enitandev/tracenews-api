import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.heartbeat import check_feed_heartbeat, check_briefing_heartbeat, check_version_heartbeat
from app.sitemap_cache import run_sitemap_cache_job_sync
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)

sitemap_client = httpx.Client(timeout=15)

def log_scheduler_alive():
    import psutil
    process = psutil.Process(os.getpid())
    rss_mb = process.memory_info().rss / (1024 * 1024)
    logger.info(f"[heartbeat] Scheduler alive at {datetime.now(timezone.utc).isoformat()} - RSS: {rss_mb:.1f}MB")


scheduler = BackgroundScheduler()


def run_sitemap_health_check():
    """
    Daily check that all sitemaps 
    have URLs. Logs an error if 
    any sitemap is empty so it 
    shows in Railway logs.
    """
    base = "https://tracenews.ng"
    sitemaps_to_check = [
        "/sitemap-stories.xml",
        "/sitemap-outlets.xml",
        "/sitemap-politicians.xml",
        "/sitemap-static.xml",
        "/news-sitemap.xml"
    ]
    
    for path in sitemaps_to_check:
        try:
            r = sitemap_client.get(
                f"{base}{path}"
            )
            count = r.text.count(
                "<url>"
            )
            if count == 0:
                logger.error(
                    f"SITEMAP HEALTH "
                    f"ALERT: {path} "
                    f"returned 0 URLs!"
                )
            else:
                logger.info(
                    f"Sitemap health "
                    f"OK: {path} has "
                    f"{count} URLs"
                )
        except Exception as e:
            logger.error(
                f"SITEMAP HEALTH "
                f"ALERT: {path} "
                f"failed: {e}"
            )


def start_scheduler():
    # NOTE: Batch jobs (fetch, cluster, score, framing, hydration, briefing)
    # have been moved to app/worker.py, run as a Railway Cron service every 20 min.
    # This scheduler only runs lightweight monitoring and sitemap jobs.

    # Sitemap Health Check — daily at 7:00 AM WAT = 6:00 AM UTC
    scheduler.add_job(
        run_sitemap_health_check,
        "cron",
        hour=6,
        minute=0,
        id="run_sitemap_health_check",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300
    )

    # Feed heartbeat — every 30 min, catches a stalled feed within the hour
    scheduler.add_job(
        check_feed_heartbeat,
        "interval",
        minutes=30,
        id="check_feed_heartbeat",
        replace_existing=True,
    )

    # Briefing heartbeat — checked once at 07:00 WAT (06:00 UTC), one hour
    # after generation is supposed to complete at 06:30 WAT
    scheduler.add_job(
        check_briefing_heartbeat,
        "cron",
        hour=6,
        minute=0,
        id="check_briefing_heartbeat",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )

    # Scheduler tripwire logging — reports RSS every 5 min
    scheduler.add_job(
        log_scheduler_alive,
        "interval",
        minutes=5,
        id="log_scheduler_alive",
        replace_existing=True,
    )

    scheduler.add_job(
        check_version_heartbeat,
        "interval",
        minutes=15,
        id="check_version_heartbeat",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc)
    )

    # Background Stories Sitemap Generation
    # Runs immediately on startup (next_run_time=now), then every 30 mins
    scheduler.add_job(
        run_sitemap_cache_job_sync,
        "interval",
        minutes=30,
        id="run_sitemap_cache_job",
        replace_existing=True,
        next_run_time=datetime.now(timezone.utc)
    )

    scheduler.start()
    logger.info(
        "Scheduler started (web-only mode). "
        "Heartbeats every 30 min, sitemap every 30 min. "
        "Batch jobs run via separate worker cron service."
    )

def stop_scheduler():
    scheduler.shutdown()

