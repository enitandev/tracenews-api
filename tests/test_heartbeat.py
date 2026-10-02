import app.heartbeat as hb


class _Q:
    def __init__(self, rows):
        self.data = rows

    def __getattr__(self, _name):
        return lambda *a, **k: self

    def execute(self):
        return self


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _Q(self.rows)


def _run(monkeypatch, rows):
    sent = []
    monkeypatch.setattr(hb, "supabase", _DB(rows))
    monkeypatch.setattr(hb, "send_alert", lambda subject, body: sent.append((subject, body)))
    hb.check_briefing_heartbeat()
    return sent


def test_alerts_when_no_rows_exist(monkeypatch):
    sent = _run(monkeypatch, [])
    assert len(sent) == 1 and "no daily briefing today" in sent[0][0]


def test_alerts_on_rows_stuck_pending_or_generating(monkeypatch):
    sent = _run(monkeypatch, [
        {"position": 1, "generation_status": "complete"},
        {"position": 2, "generation_status": "pending"},
        {"position": 3, "generation_status": "generating"},
    ])
    assert len(sent) == 1
    assert "2 of 3" in sent[0][1] and "pending: positions [2]" in sent[0][1] and "generating: positions [3]" in sent[0][1]


def test_alerts_on_failed_rows(monkeypatch):
    sent = _run(monkeypatch, [{"position": 1, "generation_status": "failed"}])
    assert len(sent) == 1 and "failed: positions [1]" in sent[0][1]


def test_silent_when_every_row_complete(monkeypatch):
    sent = _run(monkeypatch, [{"position": i, "generation_status": "complete"} for i in range(1, 4)])
    assert sent == []
