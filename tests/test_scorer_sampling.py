import app.behavioral_analyzer as ba


class _Q:
    def __init__(self, rows):
        self.rows, self.r = rows, (0, 99)

    def __getattr__(self, _):
        return lambda *a, **k: self

    def range(self, a, b):
        self.r = (a, b)
        return self

    def execute(self):
        return type("R", (), {"data": self.rows[self.r[0]:self.r[1] + 1]})()


def _with_stories(monkeypatch, n):
    rows = [{"id": i} for i in range(n)]
    monkeypatch.setattr(ba, "supabase", type("DB", (), {"table": lambda self, t: _Q(rows)})())


def test_below_minimum_is_not_scored(monkeypatch):
    _with_stories(monkeypatch, ba.MIN_ELIGIBLE_STORIES - 1)
    assert ba.fetch_sample(1) == ([], "Insufficient Data")


def test_sample_is_capped(monkeypatch):
    _with_stories(monkeypatch, 400)
    sample, confidence = ba.fetch_sample(1)
    assert len(sample) == ba.SAMPLE_CAP and confidence == "High Confidence"


def test_unjudged_article_is_not_counted_as_copy(monkeypatch):
    monkeypatch.setattr(ba, "ask_llm", lambda *a: None)
    assert ba.analyze_article({"id": "s", "title": "t"})["judged"] is False


def test_scoring_refused_under_record_hold(monkeypatch):
    import app.clusterer as clusterer
    monkeypatch.setattr(clusterer, "RECORD_HOLD", True)
    monkeypatch.setattr(ba, "supabase", None)  # any database call would raise
    ba.main(["x"])
