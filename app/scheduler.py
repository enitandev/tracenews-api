import os
import logging
from apscheduler.schedulers.background import BackgroundScheduler
from app.fetcher import run_fetch
from app.clusterer import run_clustering

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def fetch_and_cluster():
    try:
        fetch_result = run_fetch()
        logger.info(f"Fetch result: {fetch_result}")
        cluster_result = run_clustering()
        logger.info(f"Cluster result: {cluster_result}")
    except Exception as e:
        logger.error(f"Scheduled job failed: {e}")


def start_scheduler():
    interval = int(os.environ.get("FETCH_INTERVAL_MINUTES", 30))
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
