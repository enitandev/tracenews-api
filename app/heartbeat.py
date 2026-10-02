import os
import logging
import smtplib
import time
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
import requests
from app.db import supabase
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

ALERT_TO = "enitan@tracenews.ng"          # CONFIRM this address before shipping
ALERT_FROM = "enitanbello08@gmail.com"        # CONFIRM this address / domain is set up to send, not just receive

def send_alert(subject: str, body: str):
    """Minimal SMTP sender."""
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")
    if not all([smtp_host, smtp_user, smtp_pass]):
        # Fail LOUD in logs even though the whole point is we can't rely on
        # someone reading logs — this is the fallback of last resort.
        logger.error(f"[heartbeat] ALERT COULD NOT SEND (SMTP not configured): {subject} — {body}")
        return
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = ALERT_FROM
    msg["To"] = ALERT_TO
    msg.set_content(body)
    try:
        with smtplib.SMTP_SSL(smtp_host, 465, timeout=20) as s:
            s.login(smtp_user, smtp_pass)
            s.send_message(msg)
    except Exception:
        # Never let a delivery failure swallow the alert: the full alert goes
        # to the logs, and the calling heartbeat keeps running.
        logger.exception(f"[heartbeat] ALERT COULD NOT SEND (SMTP delivery failed): {subject} — {body}")
        return
    logger.info(f"[heartbeat] Alert sent: {subject}")


FEED_QUERY_ATTEMPTS = 2
FEED_QUERY_RETRY_DELAY_S = 5


def _latest_story_rows():
    """
    The newest story row. A dropped Supabase connection ('Server
    disconnected') is retried once before it counts as a failure: those
    blips were the cause of every 'feed heartbeat check itself failed'
    alert in Sep 2026, not a stalled feed.
    """
    for attempt in range(1, FEED_QUERY_ATTEMPTS + 1):
        try:
            return (
                supabase.table("stories")
                .select("created_at")
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
        except Exception:
            if attempt == FEED_QUERY_ATTEMPTS:
                raise
            logger.warning(f"[heartbeat] Feed query failed (attempt {attempt}), retrying", exc_info=True)
            time.sleep(FEED_QUERY_RETRY_DELAY_S)


def check_feed_heartbeat():
    try:
        res = _latest_story_rows()
        if not res.data:
            send_alert("TraceNews ALERT: no stories in database at all", "stories table is empty.")
            return
        last = datetime.fromisoformat(res.data[0]["created_at"])
        age_minutes = (datetime.now(timezone.utc) - last).total_seconds() / 60
        if age_minutes > 30:
            send_alert(
                "TraceNews ALERT: feed appears stalled",
                f"Last story ingested {age_minutes:.0f} minutes ago (threshold: 30). "
                f"Last story timestamp: {res.data[0]['created_at']}."
            )
        else:
            logger.info(f"[heartbeat] Feed OK — last story {age_minutes:.0f} min ago")
    except Exception as e:
        send_alert("TraceNews ALERT: feed heartbeat check itself failed", str(e))


def check_version_heartbeat():
    try:
        live_res = requests.get("https://uvicorn-appmain-production-79c6.up.railway.app/version", timeout=10)
        if not live_res.ok:
            send_alert("TraceNews ALERT: /version endpoint unreachable", f"Status {live_res.status_code}")
            return
            
        live_sha = live_res.json().get("sha")
        
        if live_sha == "unknown":
            send_alert("TraceNews ALERT: version SHA is unknown", "RAILWAY_GIT_COMMIT_SHA not injected at runtime.")
            return
            
        github_url = "https://api.github.com/repos/enitandev/tracenews-api/commits/main"
        gh_res = requests.get(github_url, timeout=10)
        if not gh_res.ok:
            logger.warning(f"Failed to fetch GitHub API to verify version: {gh_res.status_code}")
            return
            
        latest_sha = gh_res.json().get("sha")
        
        if live_sha != latest_sha:
            send_alert(
                "TraceNews ALERT: deployment stale", 
                f"Live process is running {live_sha}, but latest on main is {latest_sha}. The deploy may have crashed silently."
            )
        else:
            logger.info(f"[heartbeat] Version OK — live is {live_sha}")
    except Exception as e:
        send_alert("TraceNews ALERT: version heartbeat check itself failed", str(e))


def check_briefing_heartbeat():
    """
    Runs after the worker's briefing window (05:00-06:59 UTC) has closed.
    Today's briefing is healthy only if rows exist and every one is
    'complete'. Missing rows (selection skipped or never ran) and rows left
    'pending' or 'generating' alert too — the worker retries only 'pending'
    rows inside the window, so none of these recover on their own.
    """
    try:
        lagos_now = datetime.now(timezone.utc) + timedelta(hours=1)
        today = lagos_now.date().isoformat()
        res = (
            supabase.table("daily_briefings")
            .select("position, generation_status")
            .eq("date", today)
            .execute()
        )
        rows = res.data or []
        if not rows:
            send_alert(
                "TraceNews ALERT: no daily briefing today",
                f"No daily_briefings rows exist for {today} as of {lagos_now.strftime('%H:%M')} WAT. "
                f"Selection was skipped (fewer than 3 eligible clusters) or the worker did not run "
                f"in the 05:00-06:59 UTC window."
            )
            return
        not_complete = [r for r in rows if r.get("generation_status") != "complete"]
        if not_complete:
            by_status = {}
            for r in not_complete:
                by_status.setdefault(r.get("generation_status"), []).append(r.get("position"))
            detail = "; ".join(f"{status}: positions {sorted(p for p in positions if p is not None)}"
                               for status, positions in by_status.items())
            send_alert(
                "TraceNews ALERT: daily briefing incomplete",
                f"{len(not_complete)} of {len(rows)} daily_briefings rows for {today} are not complete "
                f"as of {lagos_now.strftime('%H:%M')} WAT ({detail}). They require manual intervention."
            )
        else:
            logger.info(f"[heartbeat] Briefing OK for {today}: {len(rows)} rows complete")
    except Exception as e:
        logger.exception("[heartbeat] briefing heartbeat check failed")
        send_alert("TraceNews ALERT: briefing heartbeat check itself failed", str(e))
