"""
Staff notifications: the Desk's record of what needs attention.

A notification is a condition, not an event. "Correction X is open", "the
feed has had no new story for two hours": while the condition holds there is
exactly one open row for it (keyed by dedupe_key), updated in place; when it
clears, the row is resolved. So a problem that lasts all afternoon is one
notification, never a stream of identical emails.

The rules that keep it quiet and trustworthy:

- Producers are state-based (app/notification_checks.py): every few minutes
  they read the database, say which conditions hold now, and sync() raises
  the new ones and resolves the ones that have cleared. A missed run or a
  crashed hook is repaired by the next run.
- A producer that fails resolves nothing (its conditions are unknown, not
  clear) and its exception is logged.
- Severity only moves people when it rises: a condition that escalates (a
  correction passes its deadline) becomes unread again for everyone.
- A condition that clears and comes back within REOPEN_WITHIN_MINUTES reopens
  its old row silently instead of announcing itself again (flapping).
- Email is opt-in per person, for urgent notifications only, at most once per
  condition every EMAIL_REPEAT_HOURS. Everything else lives in the Desk.
"""
import logging
from datetime import datetime, timedelta, timezone

from app.db import supabase
from app.permissions import has_permission

logger = logging.getLogger(__name__)

TABLE = "staff_notifications"
READS = "staff_notification_reads"
PREFS = "staff_notification_prefs"

SEVERITY_RANK = {"info": 0, "action": 1, "urgent": 2}
REOPEN_WITHIN_MINUTES = 30
EMAIL_REPEAT_HOURS = 6
# Event notifications (something happened, with no state to re-check, such
# as the AI provider refusing a request) resolve after this long without a
# recurrence.
EVENT_EXPIRES_HOURS = 6
SITE = "https://tracenews.ng"

# Fields a spec may carry; anything else is a programming error.
SPEC_FIELDS = {"key", "kind", "severity", "section", "title", "body", "link", "meta", "event"}


def _now():
    return datetime.now(timezone.utc)


def _iso(t):
    return t.isoformat()


def _parse(iso):
    return datetime.fromisoformat(iso.replace("Z", "+00:00")) if iso else None


def _check(spec):
    unknown = set(spec) - SPEC_FIELDS
    if unknown:
        raise ValueError(f"unknown notification fields: {sorted(unknown)}")
    for field in ("key", "kind", "severity", "section", "title"):
        if not spec.get(field):
            raise ValueError(f"notification is missing {field}")
    if spec["severity"] not in SEVERITY_RANK:
        raise ValueError(f"unknown severity {spec['severity']!r}")


def open_rows(prefix=""):
    """Open notifications whose key starts with prefix, by key."""
    q = supabase.table(TABLE).select("*").is_("resolved_at", "null")
    if prefix:
        q = q.like("dedupe_key", f"{prefix}%")
    return {r["dedupe_key"]: r for r in (q.execute().data or [])}


_MISSING = object()


def notify(spec, existing=_MISSING):
    """
    Raise (or refresh) the condition a spec describes. Returns the stored row.
    `existing` is the open row for the key when the caller already has it
    (sync() reads them all at once), None when it knows there is none.
    """
    _check(spec)
    key, now = spec["key"], _now()
    if existing is _MISSING:
        existing = open_rows(key).get(key)
    fields = {
        "kind": spec["kind"], "severity": spec["severity"], "section": spec["section"],
        "title": spec["title"], "body": spec.get("body"), "link": spec.get("link"),
        "meta": {**(spec.get("meta") or {}), **({"event": True} if spec.get("event") else {})},
    }

    if existing:
        changed = {k: v for k, v in fields.items() if existing.get(k) != v}
        if not changed and not spec.get("event"):
            return existing
        update = {**changed, "last_seen_at": _iso(now)}
        if spec.get("event"):
            update["occurrences"] = (existing.get("occurrences") or 1) + 1
        rose = SEVERITY_RANK[spec["severity"]] > SEVERITY_RANK.get(existing.get("severity"), 0)
        if rose:
            update["escalated_at"] = _iso(now)
        row = {**existing, **update}
        supabase.table(TABLE).update(update).eq("id", existing["id"]).execute()
        if rose:
            supabase.table(READS).delete().eq("notification_id", existing["id"]).execute()
            _maybe_email(row)
        return row

    # Flapping: the same condition cleared a moment ago. Reopen it quietly.
    cutoff = _iso(now - timedelta(minutes=REOPEN_WITHIN_MINUTES))
    recent = supabase.table(TABLE).select("*").eq("dedupe_key", key).gte("resolved_at", cutoff) \
        .order("resolved_at", desc=True).limit(1).execute().data or []
    if recent:
        update = {**fields, "resolved_at": None, "resolved_by": None, "last_seen_at": _iso(now)}
        supabase.table(TABLE).update(update).eq("id", recent[0]["id"]).execute()
        return {**recent[0], **update}

    row = {**fields, "dedupe_key": key, "first_seen_at": _iso(now), "last_seen_at": _iso(now)}
    try:
        stored = supabase.table(TABLE).insert(row).execute().data[0]
    except Exception as e:
        # Another process raised the same condition between our read and
        # insert (unique open key). Refresh that row instead.
        if "23505" not in str(e) and "duplicate" not in str(e).lower():
            raise
        return notify(spec)
    _maybe_email(stored)
    return stored


def resolve(key, by="system"):
    """Close the open notification for key, if there is one."""
    supabase.table(TABLE).update({"resolved_at": _iso(_now()), "resolved_by": by}) \
        .eq("dedupe_key", key).is_("resolved_at", "null").execute()


def sync(prefix, specs):
    """
    Make the open notifications under prefix match specs exactly: raise or
    refresh each spec, resolve every open key under prefix that is not in it.
    Call it only with a complete picture: a producer that could not read its
    data must not call sync (that would resolve everything).
    """
    for s in specs:
        if not s["key"].startswith(prefix):
            raise ValueError(f"{s['key']} is outside {prefix}")
    current = open_rows(prefix)
    wanted = {s["key"] for s in specs}
    for s in specs:
        notify(s, current.get(s["key"]))
    for key in current.keys() - wanted:
        resolve(key)
    return {"open": len(wanted), "resolved": len(current.keys() - wanted)}


def expire_events():
    """Resolve event notifications that have not recurred for EVENT_EXPIRES_HOURS."""
    cutoff = _now() - timedelta(hours=EVENT_EXPIRES_HOURS)
    for row in open_rows().values():
        if (row.get("meta") or {}).get("event") and _parse(row["last_seen_at"]) < cutoff:
            resolve(row["dedupe_key"])


# --- Reading, per person ---------------------------------------------------

def visible(row, profile):
    return has_permission(profile.get("role"), profile.get("is_staff"), row["section"], "view")


def for_you(row, me):
    """A notification addressed to this editor in particular."""
    if row["kind"] != "briefing":
        return False
    from app.routers.admin_desk import is_mine
    return is_mine(row.get("meta") or {}, me)


def inbox(user_id, profile, me, state="open"):
    """The notifications this person may see, newest first, with read state."""
    q = supabase.table(TABLE).select("*")
    if state == "open":
        q = q.is_("resolved_at", "null").order("last_seen_at", desc=True).limit(200)
    else:
        q = q.gte("resolved_at", _iso(_now() - timedelta(days=7))).order("resolved_at", desc=True).limit(100)
    rows = [r for r in (q.execute().data or []) if visible(r, profile)]
    read = set()
    if rows:
        read = {r["notification_id"] for r in (supabase.table(READS).select("notification_id")
                .eq("user_id", user_id).in_("notification_id", [r["id"] for r in rows]).execute().data or [])}
    items = [{**r, "read": r["id"] in read or state != "open", "for_you": for_you(r, me)} for r in rows]
    items.sort(key=lambda r: (r["read"], -SEVERITY_RANK[r["severity"]], not r["for_you"]))
    return items


def counts(items):
    unread = [i for i in items if not i["read"]]
    return {
        "open": len(items),
        "unread": len(unread),
        "urgent": sum(1 for i in unread if i["severity"] == "urgent"),
        "for_you": sum(1 for i in unread if i["for_you"]),
    }


def mark_read(user_id, ids):
    if not ids:
        return 0
    now = _iso(_now())
    supabase.table(READS).upsert([{"notification_id": i, "user_id": user_id, "read_at": now} for i in ids],
                                 on_conflict="notification_id,user_id").execute()
    return len(ids)


# --- Email (opt-in, urgent only) ------------------------------------------

def _recipients(section):
    prefs = supabase.table(PREFS).select("user_id, email").eq("email_urgent", True).execute().data or []
    prefs = [p for p in prefs if p.get("email")]
    if not prefs:
        return []
    profiles = {p["id"]: p for p in (supabase.table("profiles").select("id, role, is_staff")
                .in_("id", [p["user_id"] for p in prefs]).execute().data or [])}
    return [p["email"] for p in prefs
            if p["user_id"] in profiles
            and has_permission(profiles[p["user_id"]].get("role"), profiles[p["user_id"]].get("is_staff"), section, "view")]


def _maybe_email(row):
    """Email an urgent notification to the people who asked for it. A failure
    is logged with the whole notification; it never stops the producer, and
    the notification itself is already on the Desk."""
    if row.get("severity") != "urgent":
        return
    last = _parse(row.get("emailed_at"))
    if last and _now() - last < timedelta(hours=EMAIL_REPEAT_HOURS):
        return
    try:
        to = _recipients(row["section"])
        if not to:
            return
        from app.heartbeat import send_email
        link = f"{SITE}{row.get('link') or '/admin/notifications'}"
        body = (f"{row['title']}\n\n{row.get('body') or ''}\n\nOpen the Desk: {link}\n\n"
                f"You get this because you turned on urgent emails. Turn them off: {SITE}/admin/notifications")
        if send_email(to, f"TraceNews Desk: {row['title']}", body):
            supabase.table(TABLE).update({"emailed_at": _iso(_now())}).eq("id", row["id"]).execute()
    except Exception:
        logger.exception(f"[notifications] urgent email failed for {row.get('dedupe_key')}: {row.get('title')}")
