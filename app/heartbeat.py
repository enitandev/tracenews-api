import os
import logging
import smtplib
from email.message import EmailMessage
from datetime import datetime, timezone, timedelta
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
    with smtplib.SMTP_SSL(smtp_host, 465) as s:
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)
    logger.info(f"[heartbeat] Alert sent: {subject}")


def check_feed_heartbeat():
    try:
        res = (
            supabase.table("stories")
            .select("created_at")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
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


def check_briefing_heartbeat():
    try:
        lagos_now = datetime.now(timezone.utc) + timedelta(hours=1)
        today = lagos_now.date().isoformat()
        res = (
            supabase.table("daily_briefings")
            .select("id")
            .eq("date", today)
            .eq("generation_status", "complete")
            .limit(1)
            .execute()
        )
        if not res.data:
            send_alert(
                "TraceNews ALERT: daily briefing not complete",
                f"No complete daily_briefings row found for {today} as of "
                f"{lagos_now.strftime('%H:%M')} WAT. Expected by 06:30 WAT."
            )
        else:
            logger.info(f"[heartbeat] Briefing OK for {today}")
    except Exception as e:
        send_alert("TraceNews ALERT: briefing heartbeat check itself failed", str(e))
