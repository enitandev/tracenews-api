import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.fetcher import run_fetch
from app.clusterer import run_clustering
from app.scorer import run_scoring
from app.image_hydrator import run_image_hydration

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def run_fetch_job():
    try:
        fetch_result = run_fetch()
        logger.info(f"Fetch result: {fetch_result}")
    except Exception as e:
        logger.error(f"Fetch job failed: {e}")


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
    )
    
    # 2. Process Job - Can take longer, runs independently
    scheduler.add_job(
        run_process_job,
        "interval",
        minutes=interval,
        id="run_process_job",
        replace_existing=True,
    )
    
    scheduler.start()
    logger.info(f"Scheduler started. Fetch and Process jobs running independently every {interval} minutes.")


def stop_scheduler():
    scheduler.shutdown()
