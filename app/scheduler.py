from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.fetcher import run_fetch
from app.clusterer import run_clustering
from app.scorer import run_scoring
from app.image_hydrator import run_image_hydration
from app.framer import run_framing_job
from app.daily_briefing import (
    select_daily_briefing_stories,
    generate_briefing_for_story
)
from app.heartbeat import check_feed_heartbeat, check_briefing_heartbeat
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


def run_fetch_job():
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(run_fetch)
    try:
        result = future.result(timeout=480)  # 8 minute max
        logger.info(f"Fetch result: {result}")
    except FuturesTimeoutError:
        logger.error("[fetch] Job timed out after 8 minutes - proceeding without blocking")
    except Exception as e:
        logger.error(f"[fetch] Job failed: {e}")
    finally:
        executor.shutdown(wait=False)


def run_process_job():
    try:
        cluster_result = run_clustering()
        logger.info(f"Cluster result: {cluster_result}")
        
        score_result = run_scoring()
        logger.info(f"Score result: {score_result}")
        
        scheduler.add_job(run_image_hydration, id="hydrate_images_job", replace_existing=True)
    except Exception as e:
        logger.error(f"Process job failed: {e}")


def run_daily_briefing_selection():
    try:
        logger.info(
            "[scheduler] Running daily "
            "briefing story selection..."
        )
        result = select_daily_briefing_stories()
        logger.info(
            f"[scheduler] Briefing selection: "
            f"{result}"
        )
    except Exception as e:
        logger.error(
            f"[scheduler] Briefing selection "
            f"failed: {e}"
        )


def run_daily_briefing_generation():
    try:
        from datetime import datetime, timezone, timedelta
        from app.db import supabase
        
        lagos_now = datetime.now(timezone.utc) + timedelta(hours=1)
        today = lagos_now.date().isoformat()
        
        rows = supabase.table(
            "daily_briefings"
        ).select("*")\
        .eq("date", today)\
        .eq("generation_status", "pending")\
        .order("position")\
        .execute()
        
        pending = rows.data or []
        logger.info(
            f"[scheduler] Generating briefings "
            f"for {len(pending)} stories..."
        )
        
        for row in pending:
            result = generate_briefing_for_story(
                row
            )
            logger.info(
                f"[scheduler] Position "
                f"{row['position']}: "
                f"{result['status']}"
            )
            
    except Exception as e:
        logger.error(
            f"[scheduler] Briefing generation "
            f"failed: {e}"
        )


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
    interval = int(os.environ.get("FETCH_INTERVAL_MINUTES", 10))
    
    # 1. Fetch Job - High priority, runs strictly on schedule
    scheduler.add_job(
        run_fetch_job,
        "interval",
        minutes=interval,
        id="run_fetch_job",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60
    )
    
    # 2. Process Job - Can take longer, runs independently
    scheduler.add_job(
        run_process_job,
        "interval",
        minutes=interval,
        id="run_process_job",
        replace_existing=True,
    )
    
    # 3. Framing Job - Runs every 30 minutes independently
    scheduler.add_job(
        run_framing_job,
        "interval",
        minutes=30,
        id="run_framing_job",
        replace_existing=True,
    )
    
    # Daily Briefing Selection
    # Runs at 6:00 AM WAT = 5:00 AM UTC
    scheduler.add_job(
        run_daily_briefing_selection,
        "cron",
        hour=5,
        minute=0,
        id="run_daily_briefing_selection",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300
    )

    # Daily Briefing Generation  
    # Runs at 6:30 AM WAT = 5:30 AM UTC
    scheduler.add_job(
        run_daily_briefing_generation,
        "cron",
        hour=5,
        minute=30,
        id="run_daily_briefing_generation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300
    )

    # Sitemap Health Check
    # Runs at 7:00 AM WAT = 6:00 AM UTC
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

    # Scheduler tripwire logging
    scheduler.add_job(
        log_scheduler_alive,
        "interval",
        minutes=5,
        id="log_scheduler_alive",
        replace_existing=True,
    )

    scheduler.start()
    logger.info(
        "Scheduler started. Fetch and Process "
        "jobs running every 10 minutes. "
        "Daily Briefing selection at 6AM WAT, "
        "generation at 6:30AM WAT."
    )

def stop_scheduler():
    scheduler.shutdown()
