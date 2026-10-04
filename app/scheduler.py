import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.heartbeat import send_alert
from app.notification_checks import CHECK_MINUTES, run_checks, sitemap_result
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
            r = sitemap_client.get(f"{base}{path}")
            count = r.text.count("<url>")
            problem = None if count else f"{path} returned no URLs (HTTP {r.status_code})."
        except Exception as e:
            problem = f"{path} could not be fetched: {e}"
        if problem:
            logger.error(f"SITEMAP HEALTH ALERT: {problem}")
        else:
            logger.info(f"Sitemap health OK: {path} has {count} URLs")
        try:
            sitemap_result(path, problem)
        except Exception:
            logger.exception(f"[notifications] could not record the sitemap result for {path}")


# Variables Railway injects into every deployment. RAILWAY_GIT_COMMIT_SHA is
# confirmed present in production (GET /version reports it).
RAILWAY_MARKER_VARS = (
    "RAILWAY_GIT_COMMIT_SHA",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_ENVIRONMENT_NAME",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_SERVICE_ID",
)


def scheduler_should_run(env=None):
    """
    The scheduler (heartbeats, alerts, sitemap cache) runs only in the
    deployed web service. A copy of the API started locally would otherwise
    run the same production heartbeats and send alerts from a laptop, which
    is what produced the Sep 2026 alert emails.

    SCHEDULER_ENABLED=1/0 overrides the detection either way.
    Returns (should_run, reason).
    """
    env = os.environ if env is None else env
    flag = env.get("SCHEDULER_ENABLED")
    if flag is not None and flag.strip() != "":
        return flag.strip().lower() in ("1", "true", "yes", "on"), "SCHEDULER_ENABLED"
    for var in RAILWAY_MARKER_VARS:
        if env.get(var):
            return True, var
    return False, "not running on Railway"


def scheduler_running() -> bool:
    return scheduler.running


def start_scheduler():
    should_run, reason = scheduler_should_run()
    if not should_run:
        logger.warning(
            f"Scheduler NOT started ({reason}): no heartbeats, alerts or sitemap "
            f"cache job in this process. Set SCHEDULER_ENABLED=1 to force it on."
        )
        return
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

    # Staff notifications (app/notification_checks.py): Briefing approvals,
    # corrections, held politicians, feed, worker, deploy and Briefing build.
    # They appear on the Desk; nothing is emailed unless a person opted in.
    # Replaces the feed, version and briefing heartbeat emails.
    scheduler.add_job(
        run_checks,
        "interval",
        minutes=CHECK_MINUTES,
        id="run_notification_checks",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )

    # Scheduler tripwire logging — reports RSS every 5 min
    scheduler.add_job(
        log_scheduler_alive,
        "interval",
        minutes=5,
        id="log_scheduler_alive",
        replace_existing=True,
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
        f"Scheduler started (web-only mode, enabled by {reason}). "
        f"Notification checks every {CHECK_MINUTES} min, sitemap every 30 min. "
        "Batch jobs run via separate worker cron service."
    )

    # One-off delivery check: set ALERT_TEST_ON_START=1 on the service, let it
    # redeploy, confirm the email arrives, then remove the variable (it sends
    # on every start while set). Runs as a job so startup is never delayed.
    if os.environ.get("ALERT_TEST_ON_START", "").strip() == "1":
        scheduler.add_job(
            send_alert,
            "date",
            run_date=datetime.now(timezone.utc),
            args=[
                "TraceNews test alert",
                "If you can read this, production alert delivery works. "
                "Remove ALERT_TEST_ON_START from the service variables.",
            ],
            id="alert_test_on_start",
            replace_existing=True,
        )
        logger.info("[heartbeat] ALERT_TEST_ON_START is set: sending a test alert")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown()

