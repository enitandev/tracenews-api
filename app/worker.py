"""
Standalone batch worker for TraceNews.

Runs: fetch -> cluster -> score -> hydrate -> frame -> briefing (time-gated)
Exits when done. Designed to be triggered by Railway Cron every 20 minutes.

Overlap prevention: uses a database lock row in worker_locks.
If a previous run is still active (locked_at < 18 min old), this run exits immediately.
"""
import sys
import os
import logging
import traceback
from datetime import datetime, timezone, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
)
logger = logging.getLogger("worker")


def get_rss_mb():
    """Return current RSS in MB."""
    try:
        import psutil
        return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
    except Exception:
        return -1


def acquire_lock(supabase) -> bool:
    """
    Attempt to acquire the worker lock.
    Returns True if lock acquired, False if another run is active.
    """
    now = datetime.now(timezone.utc)
    try:
        lock_res = (
            supabase.table("worker_locks")
            .select("locked_at")
            .eq("job_name", "batch_worker")
            .limit(1)
            .execute()
        )
    except Exception as e:
        # Table might not exist yet - proceed without lock
        logger.warning(f"[worker] Lock table check failed (proceeding anyway): {e}")
        return True

    if lock_res.data and lock_res.data[0].get("locked_at"):
        locked_at_str = lock_res.data[0]["locked_at"]
        locked_at = datetime.fromisoformat(locked_at_str.replace("Z", "+00:00"))
        age_minutes = (now - locked_at).total_seconds() / 60

        if age_minutes < 40:
            logger.info(
                f"[worker] Previous run still active ({age_minutes:.1f} min ago). Skipping."
            )
            return False
        else:
            logger.warning(
                f"[worker] Stale lock detected ({age_minutes:.1f} min old). Taking over."
            )
            supabase.table("worker_locks").update(
                {"locked_at": now.isoformat()}
            ).eq("job_name", "batch_worker").execute()
    elif lock_res.data:
        # Row exists but locked_at is null (previous run completed cleanly)
        supabase.table("worker_locks").update(
            {"locked_at": now.isoformat()}
        ).eq("job_name", "batch_worker").execute()
    else:
        # No row exists yet - first run ever
        supabase.table("worker_locks").insert(
            {"job_name": "batch_worker", "locked_at": now.isoformat()}
        ).execute()

    return True


def release_lock(supabase):
    """Release the worker lock by clearing locked_at."""
    try:
        supabase.table("worker_locks").update(
            {"locked_at": None}
        ).eq("job_name", "batch_worker").execute()
    except Exception as e:
        logger.warning(f"[worker] Failed to release lock: {e}")


def main():
    start_time = datetime.now(timezone.utc)
    logger.info(f"[worker] Starting. PID={os.getpid()}, RSS={get_rss_mb():.1f}MB")

    from app.db import supabase

    # --- Overlap prevention ---
    if not acquire_lock(supabase):
        sys.exit(0)

    try:
        # 1. Fetch - no ThreadPoolExecutor, no timeout wrapper. Direct call.
        from app.fetcher import run_fetch
        logger.info("[worker] === FETCH ===")
        fetch_result = run_fetch()
        logger.info(f"[worker] Fetch done: {fetch_result}")

        # 2. Cluster
        from app.clusterer import run_clustering
        logger.info("[worker] === CLUSTER ===")
        cluster_result = run_clustering()
        logger.info(f"[worker] Cluster done: {cluster_result}")

        # 3. Score
        from app.scorer import run_scoring
        logger.info("[worker] === SCORE ===")
        score_result = run_scoring()
        logger.info(f"[worker] Score done: {score_result}")

        # 4. Image Hydration
        from app.image_hydrator import run_image_hydration
        logger.info("[worker] === IMAGE HYDRATION ===")
        run_image_hydration()
        logger.info("[worker] Image hydration done.")

        # 6. Daily Briefing - only during 05:00-07:00 UTC (6-8 AM WAT)
        lagos_now = datetime.now(timezone.utc) + timedelta(hours=1)
        if 5 <= datetime.now(timezone.utc).hour <= 6:
            from app.daily_briefing import (
                select_daily_briefing_stories,
                generate_briefing_for_story,
            )
            logger.info("[worker] === DAILY BRIEFING ===")
            try:
                select_daily_briefing_stories()
                today = lagos_now.date().isoformat()
                rows = (
                    supabase.table("daily_briefings")
                    .select("*")
                    .eq("date", today)
                    .eq("generation_status", "pending")
                    .order("position")
                    .execute()
                )
                for row in rows.data or []:
                    result = generate_briefing_for_story(row)
                    logger.info(
                        f"[worker] Briefing position {row.get('position')}: "
                        f"{result.get('status', 'unknown')}"
                    )
            except Exception as e:
                logger.error(f"[worker] Daily briefing failed: {e}")
        else:
            logger.info("[worker] Skipping daily briefing (outside 05-07 UTC window).")

        # 7. Update public one-tier feed (Cache for Reader Summary & Admin Overview)
        logger.info("[worker] === PUBLIC FEED CACHING ===")
        try:
            from app.routers.monitoring_spirit_admin import list_current_verdicts
            import asyncio
            loop = asyncio.get_event_loop()
            verdicts = loop.run_until_complete(list_current_verdicts("bypass"))
            public_one_tier = [v for v in verdicts if v.get("verdict") == "dark"][:5]
            
            now_iso = datetime.now(timezone.utc).isoformat()
            # Cache the full verdicts for admin overview
            supabase.table("public_feeds").upsert({
                "feed_key": "monitoring_spirit_verdicts",
                "payload": verdicts,
                "computed_at": now_iso
            }).execute()
            
            # Cache the 5 stories for reader summary
            supabase.table("public_feeds").upsert({
                "feed_key": "public_one_tier_stories",
                "payload": public_one_tier,
                "computed_at": now_iso
            }).execute()
            logger.info("[worker] Public feeds cached.")
        except Exception:
            logger.exception("public_feeds cache write failed")

        elapsed = (datetime.now(timezone.utc) - start_time).total_seconds()
        logger.info(
            f"[worker] All jobs complete in {elapsed:.0f}s. "
            f"RSS={get_rss_mb():.1f}MB"
        )

    except Exception as e:
        logger.error(f"[worker] Fatal error: {e}")
        logger.error(traceback.format_exc())
        sys.exit(1)
    finally:
        release_lock(supabase)


if __name__ == "__main__":
    main()
