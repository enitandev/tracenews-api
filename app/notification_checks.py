"""
What raises staff notifications. Each check reads the database, states which
conditions hold now, and hands them to app.notifications.sync(), which
raises new ones and resolves the ones that have cleared. Runs every
CHECK_MINUTES from the web process's scheduler, and right after an editor
acts (run_work_soon) so the bell reflects the action.

These replace the heartbeat emails of Sep-Oct 2026 ("feed appears stalled",
"deployment stale"), which fired on every check while a problem lasted and
used thresholds tighter than the worker's own 20-minute cycle.
"""
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

import requests

from app import notifications as n
from app.db import supabase

logger = logging.getLogger(__name__)

CHECK_MINUTES = 5

# Platform thresholds, in minutes. The worker runs every 20 minutes, so one
# missed run is normal; these are two to three missed runs (action) and most
# of an afternoon (urgent).
FEED_ACTION_MINUTES = 90
FEED_URGENT_MINUTES = 240
WORKER_ACTION_MINUTES = 70
WORKER_URGENT_MINUTES = 180
# A newer commit on main that is not live after this long: Railway's build
# and deploy take a few minutes; half an hour means it failed.
DEPLOY_LATE_MINUTES = 30
DEPLOY_CHECK_MINUTES = 15
# The worker builds the Briefing between 06:00 and 07:59 WAT (05:00-06:59 UTC).
# Judged in Lagos time: from 00:00 WAT the Lagos date is already tomorrow,
# whose edition is not due until morning.
BRIEFING_BUILT_BY_WAT_HOUR = 8
WAT = timezone(timedelta(hours=1))
# A check that fails this many runs in a row is itself a notification.
CHECK_FAILURES_BEFORE_NOTICE = 3
# A correction due within this many hours says so.
CORRECTION_DUE_SOON_HOURS = 3

LIVE_SHA_URL = "https://api.github.com/repos/enitandev/tracenews-api/commits/main"

_failures = {}      # check name -> consecutive failures (this process)
_since = {}         # condition -> first time this process saw it
_deploy = {"checked": 0.0, "main": None}


def _now():
    return datetime.now(timezone.utc)


def _minutes_since(iso):
    if not iso:
        return None
    return (_now() - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 60


def _human(minutes):
    if minutes < 90:
        return f"{round(minutes)} minutes"
    hours = minutes / 60
    return f"{hours:.1f} hours" if hours < 48 else f"{round(hours / 24)} days"


def _name(editor):
    return (editor or "").split(" (")[0]


# --- Work: what editors need to act on -------------------------------------

def briefing_specs(items, date):
    from app.routers.admin_desk import briefing_waiting
    waiting, _ = briefing_waiting([i for i in items if not i.get("is_sample")], None)
    specs = []
    for i in waiting:
        first = i.get("approved_by")
        second = first and i.get("needs_second_approver")
        specs.append({
            "key": f"briefing:{date}:{i['id']}", "kind": "briefing", "section": "briefing",
            "severity": "action",
            "title": f"Briefing: {i.get('title') or 'an item'}",
            "body": (f"Approved by {_name(first)}. Needs a second approval from {i.get('waiting_for') or 'another editor'}."
                     if second else
                     "Needs a senior editor’s review before it can be published." if i.get("lane") == "senior_review"
                     else "Needs an editor’s approval before it can be published."),
            "link": "/admin/briefing",
            "meta": {"date": date, "item_id": i["id"], "lane": i.get("lane"), "approved_by": first,
                     "needs_second_approver": bool(i.get("needs_second_approver"))},
        })
    return specs


SUBJECT = {"cluster_summary": "Story summary", "outlet": "Outlet", "politician": "Politician page",
           "page": "Page", "briefing": "Daily Briefing"}


def correction_specs(rows):
    now = _now()
    specs = []
    for r in rows:
        due = datetime.fromisoformat(r["sla_due_at"].replace("Z", "+00:00")) if r.get("sla_due_at") else None
        if due and due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        subject = SUBJECT.get(r.get("subject_type"), r.get("subject_type") or "Page")
        if due and due < now:
            severity, body = "urgent", f"Past its deadline by {_human((now - due).total_seconds() / 60)}."
        elif due and due - now < timedelta(hours=CORRECTION_DUE_SOON_HOURS):
            severity, body = "action", f"Due in {_human((due - now).total_seconds() / 60)}."
        else:
            severity, body = "action", "New request from a reader." if r.get("status") == "new" else "Open."
        if r.get("status") == "escalated_legal":
            body = f"With legal. {body}"
        specs.append({
            "key": f"correction:{r['id']}", "kind": "correction", "section": "corrections", "severity": severity,
            "title": f"Correction: {r.get('category') or 'request'} — {subject}",
            "body": body, "link": "/admin/corrections",
            "meta": {"correction_id": r["id"], "status": r.get("status"), "due": r.get("sla_due_at")},
        })
    return specs


def politician_specs(held):
    if not held:
        return []
    return [{
        "key": "politicians:held", "kind": "politician", "section": "politicians", "severity": "info",
        "title": f"{held} politician {'page is' if held == 1 else 'pages are'} held for review",
        "body": "Held pages return 404 to readers until an editor records a decision.",
        "link": "/admin/politicians", "meta": {"held": held},
    }]


def check_work():
    """Briefing approvals, open corrections, held politician pages."""
    from app.briefing_edition import lagos_today
    from app.routers.admin_desk import OPEN_CORRECTION_STATUSES
    from app.routers.briefing import staff_items

    today = lagos_today().isoformat()
    _run("briefing", lambda: n.sync("briefing:", briefing_specs(staff_items(lagos_today()), today)))
    _run("corrections", lambda: n.sync("correction:", correction_specs(
        supabase.table("correction_requests").select("id, category, subject_type, status, sla_due_at")
        .in_("status", list(OPEN_CORRECTION_STATUSES)).limit(500).execute().data or [])))
    _run("politicians", lambda: n.sync("politicians:", politician_specs(
        supabase.table("politicians").select("id", count="exact").eq("publication_status", "pending_review")
        .limit(1).execute().count or 0)))


# --- Platform health -------------------------------------------------------

def _latest(table, column, **eq):
    q = supabase.table(table).select(column)
    for k, v in eq.items():
        q = q.eq(k, v)
    rows = q.order(column, desc=True).limit(1).execute().data or []
    return rows[0][column] if rows else None


def staleness_spec(key, minutes, action_after, urgent_after, title, what):
    if minutes is not None and minutes < action_after:
        return []
    severity = "urgent" if minutes is None or minutes >= urgent_after else "action"
    body = f"No record at all of {what}." if minutes is None else f"The last {what} was {_human(minutes)} ago."
    return [{"key": key, "kind": "health", "section": "platform_health", "severity": severity,
             "title": title, "body": body, "link": "/admin", "meta": {"minutes": None if minutes is None else round(minutes)}}]


def feed_specs():
    return staleness_spec("health:feed", _minutes_since(_latest("stories", "created_at")),
                          FEED_ACTION_MINUTES, FEED_URGENT_MINUTES, "No new stories are coming in", "story ingested")


def worker_specs():
    return staleness_spec("health:worker",
                          _minutes_since(_latest("public_feeds", "computed_at", feed_key="monitoring_spirit_verdicts")),
                          WORKER_ACTION_MINUTES, WORKER_URGENT_MINUTES, "The worker has not finished a run",
                          "completed worker run")


def deploy_specs():
    """A newer commit on main that has not gone live within DEPLOY_LATE_MINUTES.
    The live commit is this process's own (Railway sets RAILWAY_GIT_COMMIT_SHA),
    so a deploy that crashed on start leaves the old process running and
    reporting the old commit. Off Railway there is nothing to compare."""
    live = os.environ.get("RAILWAY_GIT_COMMIT_SHA")
    if not live:
        return []
    if time.time() - _deploy["checked"] >= DEPLOY_CHECK_MINUTES * 60:
        res = requests.get(LIVE_SHA_URL, timeout=10)
        res.raise_for_status()
        _deploy.update(checked=time.time(), main=res.json().get("sha"))
    main = _deploy["main"]
    if not main or main == live:
        _since.pop("deploy", None)
        return []
    first = _since.setdefault("deploy", (main, _now()))
    if first[0] != main:
        first = _since["deploy"] = (main, _now())
    waited = (_now() - first[1]).total_seconds() / 60
    if waited < DEPLOY_LATE_MINUTES:
        return []
    return [{"key": "health:deploy", "kind": "health", "section": "platform_health", "severity": "action",
             "title": "The newest code has not gone live",
             "body": f"Main is at {main[:7]} but the API is still running {live[:7]}, {_human(waited)} later. "
                     f"Check the latest deploy in Railway.",
             "link": "/admin", "meta": {"live": live[:7], "main": main[:7]}}]


def briefing_build_specs(now=None):
    lagos = (now or _now()).astimezone(WAT)
    if lagos.hour < BRIEFING_BUILT_BY_WAT_HOUR:
        return None          # not yet due: leave today's state alone
    day = lagos.date().isoformat()
    rows = supabase.table("briefing_editions").select("id").eq("date", day).eq("is_sample", False) \
        .limit(1).execute().data or []
    if rows:
        return []
    return [{"key": f"health:briefing:{day}", "kind": "health", "section": "briefing", "severity": "urgent",
             "title": "No Daily Briefing edition today",
             "body": "The worker builds it between 06:00 and 08:00 WAT. Either fewer than three stories had a "
                     "usable summary, or the worker did not run in that window.",
             "link": "/admin/briefing", "meta": {"date": day}}]


def check_health():
    _run("feed", lambda: n.sync("health:feed", feed_specs()))
    _run("worker", lambda: n.sync("health:worker", worker_specs()))
    _run("deploy", lambda: n.sync("health:deploy", deploy_specs()))

    def briefing_build():
        specs = briefing_build_specs()
        if specs is not None:
            n.sync("health:briefing:", specs)
    _run("briefing_build", briefing_build)
    _run("expire_events", n.expire_events)


def sitemap_result(path, problem):
    """Called by the daily sitemap check (app/scheduler.py)."""
    key = f"health:sitemap:{path}"
    if not problem:
        n.resolve(key)
        return
    n.notify({"key": key, "kind": "health", "section": "platform_health", "severity": "action",
              "title": f"Sitemap {path} is broken", "body": problem, "link": "/admin"})


def report_event(key, title, body, severity="urgent", section="platform_health"):
    """Something happened that has no state to re-check (the AI provider
    refused a request). Repeats update one notification; it resolves itself
    after EVENT_EXPIRES_HOURS without a recurrence. Never raises."""
    try:
        n.notify({"key": key, "kind": "health", "section": section, "severity": severity,
                  "title": title, "body": body, "link": "/admin", "event": True})
    except Exception:
        logger.exception(f"[notifications] could not record event {key}: {title} — {body}")


# --- Running ----------------------------------------------------------------

def _run(name, fn):
    """Run one check. A failure resolves nothing and is logged; repeated
    failures become a notification of their own, cleared on success."""
    try:
        fn()
    except Exception as e:
        _failures[name] = _failures.get(name, 0) + 1
        logger.exception(f"[notifications] check {name} failed ({_failures[name]} in a row)")
        if _failures[name] >= CHECK_FAILURES_BEFORE_NOTICE:
            try:
                n.notify({"key": f"health:check:{name}", "kind": "health", "section": "platform_health",
                          "severity": "action", "title": f"The {name.replace('_', ' ')} check keeps failing",
                          "body": f"{_failures[name]} runs in a row. Latest error: {str(e)[:300]}", "link": "/admin"})
            except Exception:
                logger.exception(f"[notifications] could not record that check {name} is failing")
        return False
    if _failures.pop(name, 0) >= CHECK_FAILURES_BEFORE_NOTICE:
        try:
            n.resolve(f"health:check:{name}")
        except Exception:
            logger.exception(f"[notifications] could not resolve the failing-check notice for {name}")
    return True


_lock = threading.Lock()


def run_checks():
    """Every check, once. The scheduler calls this every CHECK_MINUTES."""
    if not _lock.acquire(blocking=False):
        return
    try:
        check_work()
        check_health()
    finally:
        _lock.release()


_pending = threading.Event()


def run_work_soon():
    """Refresh the work notifications in the background after an editor acts
    or a reader sends a correction. Several calls in quick succession run once."""
    if _pending.is_set():
        return
    _pending.set()

    def go():
        time.sleep(2)
        _pending.clear()
        if _lock.acquire(blocking=False):
            try:
                check_work()
            finally:
                _lock.release()
    threading.Thread(target=go, daemon=True, name="notifications-soon").start()
