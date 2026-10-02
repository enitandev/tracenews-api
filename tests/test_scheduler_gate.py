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
