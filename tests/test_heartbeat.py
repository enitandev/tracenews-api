import app.heartbeat as hb


def test_smtp_failure_logs_the_alert_and_does_not_raise(monkeypatch, caplog):
    import logging
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    monkeypatch.setenv("SMTP_HOST", "smtp.example")
    monkeypatch.setenv("SMTP_USER", "u")
    monkeypatch.setenv("SMTP_PASS", "p")

    def unreachable(*a, **k):
        raise OSError(101, "Network is unreachable")

    monkeypatch.setattr(hb.smtplib, "SMTP_SSL", unreachable)
    with caplog.at_level(logging.ERROR, logger="app.heartbeat"):
        hb.send_alert("TraceNews ALERT: test", "the body")
    assert "ALERT COULD NOT SEND (SMTP delivery failed): TraceNews ALERT: test — the body" in caplog.text


class _Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text, self.ok = status, text, 200 <= status < 300


def test_resend_is_used_when_configured(monkeypatch, caplog):
    import logging
    calls = []
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setenv("SMTP_HOST", "smtp.example")  # present but must not be used
    monkeypatch.setattr(hb.smtplib, "SMTP_SSL", lambda *a, **k: (_ for _ in ()).throw(AssertionError("SMTP used")))
    monkeypatch.setattr(hb.requests, "post", lambda url, **kw: calls.append((url, kw)) or _Resp(200, '{"id":"x"}'))
    with caplog.at_level(logging.INFO, logger="app.heartbeat"):
        hb.send_alert("TraceNews ALERT: feed appears stalled", "Last story 45 minutes ago.")
    (url, kw), = calls
    assert url == "https://api.resend.com/emails"
    assert kw["headers"]["Authorization"] == "Bearer re_test"
    assert kw["json"] == {
        "from": hb.ALERT_FROM, "to": [hb.ALERT_TO],
        "subject": "TraceNews ALERT: feed appears stalled", "text": "Last story 45 minutes ago.",
    }
    assert "Alert sent via Resend" in caplog.text


def test_resend_rejection_logs_the_whole_alert(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("RESEND_API_KEY", "re_test")
    monkeypatch.setattr(hb.requests, "post", lambda url, **kw: _Resp(403, "domain not verified"))
    with caplog.at_level(logging.ERROR, logger="app.heartbeat"):
        hb.send_alert("TraceNews ALERT: x", "body")
    assert "ALERT COULD NOT SEND (Resend delivery failed): TraceNews ALERT: x — body" in caplog.text
    assert "domain not verified" in caplog.text


def test_no_channel_logs_the_whole_alert(monkeypatch, caplog):
    import logging
    for var in ("RESEND_API_KEY", "SMTP_HOST", "SMTP_USER", "SMTP_PASS"):
        monkeypatch.delenv(var, raising=False)
    with caplog.at_level(logging.ERROR, logger="app.heartbeat"):
        hb.send_alert("TraceNews ALERT: y", "body")
    assert "ALERT COULD NOT SEND (no email channel configured): TraceNews ALERT: y — body" in caplog.text
