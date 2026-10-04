"""Staff notifications: one row per condition, quiet by default, honest about failure."""
from datetime import datetime, timedelta, timezone

import pytest

import app.heartbeat as hb
import app.notification_checks as checks
import app.notifications as n
from tests.fakedb import FakeDB

OWNER = {"id": "u-owner", "role": "super_admin", "is_staff": True}
EDITOR = {"id": "u-tolu", "role": "editorial", "is_staff": True}
ENITAN, TOLU = "Enitan Bello (super_admin)", "Toluwalope Bello (editorial)"


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB(profiles=[OWNER, EDITOR])
    monkeypatch.setattr(n, "supabase", fake)
    monkeypatch.setattr(checks, "supabase", fake)
    sent = []
    monkeypatch.setattr(hb, "send_email", lambda to, subject, body: sent.append((sorted(to), subject)) or True)
    fake.sent = sent
    checks._failures.clear()
    checks._since.clear()
    return fake


def spec(key="correction:1", severity="action", section="corrections", **kw):
    return {"key": key, "kind": kw.pop("kind", "correction"), "severity": severity, "section": section,
            "title": kw.pop("title", "Correction: wrong date — Page"), "link": "/admin/corrections", **kw}


def opt_in(db, user, email):
    db.tables.setdefault("staff_notification_prefs", []).append(
        {"user_id": user["id"], "email": email, "email_urgent": True})


def open_rows(db):
    return [r for r in db.rows("staff_notifications") if r.get("resolved_at") is None]


# --- the engine -------------------------------------------------------------

def test_a_condition_that_persists_is_one_notification(db):
    for _ in range(12):
        n.sync("correction:", [spec()])
    rows = db.rows("staff_notifications")
    assert len(rows) == 1 and rows[0]["occurrences"] == 1


def test_a_condition_that_clears_is_resolved_by_the_system(db):
    n.sync("correction:", [spec("correction:1"), spec("correction:2")])
    n.sync("correction:", [spec("correction:2")])
    gone = [r for r in db.rows("staff_notifications") if r["dedupe_key"] == "correction:1"][0]
    assert gone["resolved_at"] and gone["resolved_by"] == "system"
    assert [r["dedupe_key"] for r in open_rows(db)] == ["correction:2"]


def test_sync_leaves_other_prefixes_alone(db):
    n.notify(spec("health:feed", section="platform_health", kind="health"))
    n.sync("correction:", [])
    assert [r["dedupe_key"] for r in open_rows(db)] == ["health:feed"]


def test_nothing_is_emailed_unless_someone_opted_in(db):
    n.notify(spec(severity="urgent"))
    assert db.sent == []


def test_urgent_email_goes_only_to_opted_in_staff_who_can_see_the_section(db):
    opt_in(db, OWNER, "enitan@tracenews.ng")
    opt_in(db, EDITOR, "tolu@tracenews.ng")
    n.notify(spec("health:feed", severity="urgent", section="platform_health", kind="health"))
    assert db.sent == [(["enitan@tracenews.ng"], "TraceNews Desk: Correction: wrong date — Page")]


def test_action_and_info_are_never_emailed(db):
    opt_in(db, OWNER, "enitan@tracenews.ng")
    n.notify(spec(severity="action"))
    n.notify(spec("politicians:held", severity="info", section="politicians"))
    assert db.sent == []


def test_escalation_makes_it_unread_again_and_emails_once(db):
    opt_in(db, OWNER, "enitan@tracenews.ng")
    row = n.notify(spec(severity="action"))
    n.mark_read(OWNER["id"], [row["id"]])
    n.notify(spec(severity="urgent"))
    assert db.rows("staff_notification_reads") == []
    assert len(db.sent) == 1
    # Repeats of the same urgent condition do not email again.
    for _ in range(5):
        n.notify(spec(severity="urgent", title="Correction: wrong date — Page (still)"))
    assert len(db.sent) == 1


def test_a_condition_that_flaps_reopens_quietly(db):
    opt_in(db, OWNER, "enitan@tracenews.ng")
    n.sync("health:feed", [spec("health:feed", severity="urgent", section="platform_health", kind="health")])
    n.sync("health:feed", [])
    n.sync("health:feed", [spec("health:feed", severity="urgent", section="platform_health", kind="health")])
    assert len(db.rows("staff_notifications")) == 1 and len(open_rows(db)) == 1
    assert len(db.sent) == 1


def test_events_count_repeats_and_expire(db, monkeypatch):
    for _ in range(3):
        checks.report_event("health:ai_quota", "The AI provider has stopped accepting requests", "billing")
    row, = db.rows("staff_notifications")
    assert row["occurrences"] == 3 and row["meta"]["event"] is True
    n.expire_events()
    assert open_rows(db)
    row["last_seen_at"] = (datetime.now(timezone.utc) - timedelta(hours=7)).isoformat()
    n.expire_events()
    assert open_rows(db) == []


def test_email_failure_never_stops_the_notification(db, monkeypatch, caplog):
    opt_in(db, OWNER, "enitan@tracenews.ng")
    monkeypatch.setattr(hb, "send_email", lambda *a: (_ for _ in ()).throw(RuntimeError("Resend down")))
    row = n.notify(spec(severity="urgent"))
    assert row["dedupe_key"] == "correction:1" and row["emailed_at"] is None
    assert "urgent email failed for correction:1" in caplog.text


def test_unknown_fields_and_severities_are_refused(db):
    with pytest.raises(ValueError):
        n.notify({**spec(), "recipient": "x"})
    with pytest.raises(ValueError):
        n.notify(spec(severity="critical"))


# --- reading ----------------------------------------------------------------

def test_each_person_sees_their_sections_with_their_own_read_state(db):
    a = n.notify(spec("health:feed", section="platform_health", kind="health", severity="urgent"))
    b = n.notify(spec("correction:1"))
    n.mark_read(OWNER["id"], [b["id"]])
    owner = n.inbox(OWNER["id"], OWNER, ENITAN)
    editor = n.inbox(EDITOR["id"], EDITOR, TOLU)
    assert [(i["id"], i["read"]) for i in owner] == [(a["id"], False), (b["id"], True)]
    assert [(i["id"], i["read"]) for i in editor] == [(b["id"], False)]
    assert n.counts(owner) == {"open": 2, "unread": 1, "urgent": 1, "for_you": 0}


def test_briefing_items_are_for_whoever_can_give_the_missing_approval(db):
    items = [
        {"id": "a", "title": "A", "lane": "review"},
        {"id": "b", "title": "B", "lane": "senior_review", "approved_by": TOLU, "needs_second_approver": True,
         "waiting_for": "Enitan Bello"},
        {"id": "c", "title": "C", "lane": "auto", "publishable": True},
        {"id": "s", "title": "S", "lane": "review", "is_sample": True},
    ]
    n.sync("briefing:", checks.briefing_specs(items, "2026-10-05"))
    owner = {i["meta"]["item_id"]: i["for_you"] for i in n.inbox(OWNER["id"], OWNER, ENITAN)}
    editor = {i["meta"]["item_id"]: i["for_you"] for i in n.inbox(EDITOR["id"], EDITOR, TOLU)}
    assert owner == {"a": True, "b": True}
    assert editor == {"a": True, "b": False}


# --- producers --------------------------------------------------------------

def test_corrections_escalate_as_their_deadline_passes():
    now = datetime.now(timezone.utc)
    rows = [
        {"id": "late", "status": "in_review", "sla_due_at": (now - timedelta(hours=2)).isoformat()},
        {"id": "soon", "status": "new", "sla_due_at": (now + timedelta(hours=1)).isoformat()},
        {"id": "fine", "status": "new", "sla_due_at": (now + timedelta(days=3)).isoformat()},
        {"id": "legal", "status": "escalated_legal", "sla_due_at": (now + timedelta(days=3)).isoformat()},
    ]
    s = {x["key"]: x for x in checks.correction_specs(rows)}
    assert s["correction:late"]["severity"] == "urgent" and "Past its deadline" in s["correction:late"]["body"]
    assert s["correction:soon"]["severity"] == "action" and s["correction:soon"]["body"].startswith("Due in")
    assert s["correction:fine"]["body"] == "New request from a reader."
    assert s["correction:legal"]["body"].startswith("With legal.")


def test_politicians_are_one_notification_and_none_when_nothing_is_held():
    assert checks.politician_specs(0) == []
    s, = checks.politician_specs(4)
    assert s["key"] == "politicians:held" and s["title"] == "4 politician pages are held for review"


@pytest.mark.parametrize("minutes,severity", [(30, None), (89, None), (90, "action"), (239, "action"),
                                              (240, "urgent"), (None, "urgent")])
def test_feed_thresholds_allow_for_the_workers_own_cycle(minutes, severity):
    s = checks.staleness_spec("health:feed", minutes, checks.FEED_ACTION_MINUTES, checks.FEED_URGENT_MINUTES,
                              "No new stories are coming in", "story ingested")
    assert (s[0]["severity"] if s else None) == severity


def test_a_new_commit_is_only_reported_if_it_stays_undeployed(monkeypatch):
    checks._since.clear()
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "a" * 40)
    checks._deploy.update(checked=0.0, main=None)

    class R:
        def raise_for_status(self):
            pass

        def json(self):
            return {"sha": "b" * 40}
    monkeypatch.setattr(checks.requests, "get", lambda *a, **k: R())
    assert checks.deploy_specs() == []                      # just pushed: Railway is building
    main, _ = checks._since["deploy"]
    checks._since["deploy"] = (main, datetime.now(timezone.utc) - timedelta(minutes=31))
    s, = checks.deploy_specs()
    assert s["severity"] == "action" and "bbbbbbb" in s["body"] and "aaaaaaa" in s["body"]


def test_no_deploy_check_off_railway(monkeypatch):
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    assert checks.deploy_specs() == []


def test_briefing_build_is_not_judged_before_it_is_due(db):
    early = datetime(2026, 10, 5, 6, 30, tzinfo=timezone.utc)
    assert checks.briefing_build_specs(early) is None
    # 23:30 UTC is 00:30 WAT on the 6th: tomorrow's edition is not due yet.
    assert checks.briefing_build_specs(datetime(2026, 10, 5, 23, 30, tzinfo=timezone.utc)) is None
    late = datetime(2026, 10, 5, 7, 5, tzinfo=timezone.utc)
    s, = checks.briefing_build_specs(late)
    assert s["severity"] == "urgent" and s["section"] == "briefing"
    assert s["key"] == "health:briefing:2026-10-05"


def test_a_failing_check_resolves_nothing_and_speaks_up_after_three_runs(db):
    n.sync("correction:", [spec("correction:1")])

    def broken():
        raise RuntimeError("Server disconnected")
    for _ in range(2):
        assert checks._run("corrections", broken) is False
    assert [r["dedupe_key"] for r in open_rows(db)] == ["correction:1"]
    checks._run("corrections", broken)
    assert {r["dedupe_key"] for r in open_rows(db)} == {"correction:1", "health:check:corrections"}
    checks._run("corrections", lambda: None)
    assert [r["dedupe_key"] for r in open_rows(db)] == ["correction:1"]
