import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.fetcher import run_fetch
from app.clusterer import run_clustering
from app.scorer import run_scoring
from app.image_hydrator import run_image_hydration

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def fetch_and_cluster():
    try:
        # 1. Fetch
        fetch_result = run_fetch()
        logger.info(f"Fetch result: {fetch_result}")
        
        # 2. Cluster
        cluster_result = run_clustering()
        logger.info(f"Cluster result: {cluster_result}")
        
        # 3. Score
        score_result = run_scoring()
        logger.info(f"Score result: {score_result}")
        
        # 4. Hydrate Images (run as a separate non-blocking job so it doesn't hold up this thread)
        scheduler.add_job(run_image_hydration, id="hydrate_images_job", replace_existing=True)
        
    except Exception as e:
        logger.error(f"Scheduled job failed: {e}")


def start_scheduler():
    interval = int(os.environ.get("FETCH_INTERVAL_MINUTES", 10))
    scheduler.add_job(
        fetch_and_cluster,
        "interval",
        minutes=interval,
        id="fetch_and_cluster",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"Scheduler started. Fetching every {interval} minutes.")


def stop_scheduler():
    scheduler.shutdown()
