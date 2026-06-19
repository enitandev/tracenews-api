from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError
import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.fetcher import run_fetch
from app.clusterer import run_clustering
from app.scorer import run_scoring
from app.image_hydrator import run_image_hydration
from app.framer import run_framing_job

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def run_fetch_job():
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_fetch)
        try:
            result = future.result(timeout=480)  # 8 minute max
            logger.info(f"Fetch result: {result}")
        except FuturesTimeoutError:
            logger.error("[fetch] Job timed out after 8 minutes - cancelling")
            future.cancel()
        except Exception as e:
            logger.error(f"[fetch] Job failed: {e}")


def run_process_job():
    try:
        cluster_result = run_clustering()
        logger.info(f"Cluster result: {cluster_result}")
        
        score_result = run_scoring()
        logger.info(f"Score result: {score_result}")
        
        scheduler.add_job(run_image_hydration, id="hydrate_images_job", replace_existing=True)
    except Exception as e:
        logger.error(f"Process job failed: {e}")


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
    
    scheduler.start()
    logger.info(f"Scheduler started. Fetch and Process jobs running every {interval} minutes. Framing job running every 30 minutes.")


def stop_scheduler():
    scheduler.shutdown()
