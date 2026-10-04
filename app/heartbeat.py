import os
import logging
import smtplib
from email.message import EmailMessage
import requests
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# enitan@tracenews.ng is an ImprovMX alias forwarding to the owner's Gmail.
ALERT_TO = os.environ.get("ALERT_TO", "enitan@tracenews.ng")
# Resend sends from the verified tracenews.ng domain.
ALERT_FROM = os.environ.get("ALERT_FROM", "TraceNews Alerts <alerts@tracenews.ng>")
# SMTP fallback (local use only: Railway's Hobby plan blocks outbound SMTP).
SMTP_FROM = os.environ.get("SMTP_FROM", "enitanbello08@gmail.com")

RESEND_API_URL = "https://api.resend.com/emails"


def _send_via_resend(api_key: str, to: list, subject: str, body: str) -> None:
    res = requests.post(
        RESEND_API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"from": ALERT_FROM, "to": to, "subject": subject, "text": body},
        timeout=20,
    )
    if not res.ok:
        raise RuntimeError(f"Resend returned {res.status_code}: {res.text[:300]}")


def _send_via_smtp(smtp_host: str, smtp_user: str, smtp_pass: str, to: list, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = SMTP_FROM
    msg["To"] = ", ".join(to)
    msg.set_content(body)
    with smtplib.SMTP_SSL(smtp_host, 465, timeout=20) as s:
        s.login(smtp_user, smtp_pass)
        s.send_message(msg)


def send_email(to: list, subject: str, body: str) -> bool:
    """
    Deliver one email: Resend's HTTPS API when RESEND_API_KEY is set
    (production), else SMTP when SMTP_* are set. A delivery that fails, or no
    channel at all, logs the whole message at ERROR and returns False; it
    never raises, so the caller keeps running. Staff notifications live on
    the Desk (app/notifications.py); email is only for people who opted in.
    """
    resend_key = os.environ.get("RESEND_API_KEY")
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_user = os.environ.get("SMTP_USER")
    smtp_pass = os.environ.get("SMTP_PASS")

    if resend_key:
        channel = "Resend"
        send = lambda: _send_via_resend(resend_key, to, subject, body)
    elif all([smtp_host, smtp_user, smtp_pass]):
        channel = "SMTP"
        send = lambda: _send_via_smtp(smtp_host, smtp_user, smtp_pass, to, subject, body)
    else:
        logger.error(f"[heartbeat] ALERT COULD NOT SEND (no email channel configured): {subject} — {body}")
        return False

    try:
        send()
    except Exception:
        logger.exception(f"[heartbeat] ALERT COULD NOT SEND ({channel} delivery failed): {subject} — {body}")
        return False
    logger.info(f"[heartbeat] Alert sent via {channel}: {subject}")
    return True


def send_alert(subject: str, body: str):
    """One email to ALERT_TO. Used only for the delivery test below and
    ALERT_TEST_ON_START; platform problems are Desk notifications now
    (app/notification_checks.py), never automatic emails."""
    return send_email([ALERT_TO], subject, body)


if __name__ == "__main__":
    # python -m app.heartbeat --test   sends one test alert through the
    # configured channel (e.g. `railway run python -m app.heartbeat --test`).
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--test" in sys.argv:
        send_alert("TraceNews test alert", "If you can read this, alert delivery works.")
    else:
        print("usage: python -m app.heartbeat --test")
