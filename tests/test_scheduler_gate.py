from app.scheduler import scheduler_should_run


def test_runs_on_railway():
    assert scheduler_should_run({"RAILWAY_GIT_COMMIT_SHA": "abc"}) == (True, "RAILWAY_GIT_COMMIT_SHA")
    assert scheduler_should_run({"RAILWAY_ENVIRONMENT_NAME": "production"})[0] is True


def test_does_not_run_locally():
    assert scheduler_should_run({"SUPABASE_URL": "x", "SMTP_HOST": "smtp.gmail.com"}) == (False, "not running on Railway")


def test_explicit_flag_overrides_detection_both_ways():
    assert scheduler_should_run({"SCHEDULER_ENABLED": "1"}) == (True, "SCHEDULER_ENABLED")
    assert scheduler_should_run({"SCHEDULER_ENABLED": "0", "RAILWAY_GIT_COMMIT_SHA": "abc"}) == (False, "SCHEDULER_ENABLED")


def test_start_scheduler_is_a_no_op_off_railway(monkeypatch, caplog):
    import logging
    import app.scheduler as sched
    for var in sched.RAILWAY_MARKER_VARS + ("SCHEDULER_ENABLED",):
        monkeypatch.delenv(var, raising=False)
    with caplog.at_level(logging.WARNING, logger="app.scheduler"):
        sched.start_scheduler()
    assert sched.scheduler_running() is False
    assert "Scheduler NOT started (not running on Railway)" in caplog.text
    sched.stop_scheduler()  # safe when never started


def test_alert_test_on_start_sends_one_alert(monkeypatch):
    import time
    import app.scheduler as sched
    sent = []
    monkeypatch.setenv("SCHEDULER_ENABLED", "1")
    monkeypatch.setenv("ALERT_TEST_ON_START", "1")
    monkeypatch.setattr(sched, "send_alert", lambda subject, body: sent.append(subject))
    # Keep the test free of network: replace the jobs that would hit the DB/HTTP.
    for name in ("run_sitemap_health_check", "run_checks",
                 "log_scheduler_alive", "run_sitemap_cache_job_sync"):
        monkeypatch.setattr(sched, name, lambda: None)
    try:
        sched.start_scheduler()
        for _ in range(50):
            if sent:
                break
            time.sleep(0.1)
    finally:
        sched.stop_scheduler()
    assert sent == ["TraceNews test alert"]


def test_no_test_alert_without_the_flag(monkeypatch):
    import app.scheduler as sched
    monkeypatch.delenv("ALERT_TEST_ON_START", raising=False)
    monkeypatch.setenv("SCHEDULER_ENABLED", "1")
    for name in ("run_sitemap_health_check", "run_checks",
                 "log_scheduler_alive", "run_sitemap_cache_job_sync"):
        monkeypatch.setattr(sched, name, lambda: None)
    try:
        sched.start_scheduler()
        assert sched.scheduler.get_job("alert_test_on_start") is None
    finally:
        sched.stop_scheduler()
