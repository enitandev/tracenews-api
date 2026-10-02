"""Classifier confidence gating: low confidence is flagged, never silently published."""
from types import SimpleNamespace
import app.classifier as classifier
from app.classifier import validate_classification


class TestValidateClassification:
    def test_valid_answer_passes_through(self):
        assert validate_classification({"category": "Politics", "confidence": 0.91}) == \
            {"category": "Politics", "confidence": 0.91, "retry": False}

    def test_unrecognised_category_is_flagged_not_absorbed(self, caplog):
        r = validate_classification({"category": "Crime", "confidence": 0.95})
        assert r == {"category": "General", "confidence": 0.0, "retry": False}
        assert "unrecognised category 'Crime'" in caplog.text

    def test_missing_category_is_flagged(self):
        assert validate_classification({"confidence": 0.9})["confidence"] == 0.0

    def test_invalid_confidence_is_flagged(self):
        for bad in ("high", None, 1.5, -0.1, True):
            r = validate_classification({"category": "Economy", "confidence": bad})
            assert r == {"category": "Economy", "confidence": 0.0, "retry": False}, bad


def _fake_openai(monkeypatch, content=None, error=None):
    def create(**kwargs):
        if error:
            raise error
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    monkeypatch.setattr(classifier.openai_client.chat.completions, "create", create)


def test_failed_call_is_retried(monkeypatch):
    _fake_openai(monkeypatch, error=RuntimeError("timeout"))
    assert classifier.classify_cluster("t", "s") == {"category": "General", "confidence": 0.0, "retry": True}


def test_unusable_answer_is_not_retried(monkeypatch):
    _fake_openai(monkeypatch, content='{"category": "Crime", "confidence": 0.9}')
    r = classifier.classify_cluster("t", "s")
    assert r["retry"] is False and r["confidence"] == 0.0


class _Q:
    def __init__(self, name, data, log):
        self.name, self.data, self.log = name, data, log

    def select(self, columns="*", *a, **k):
        # Return only the selected columns, as PostgREST does, so a column
        # the query forgets to fetch is missing here too.
        if "*" not in columns and "(" not in columns:
            cols = [c.strip() for c in columns.split(",")]
            self.data = [{c: row[c] for c in cols if c in row} for row in self.data]
        return self

    def update(self, payload):
        self.log.append((self.name, payload))
        return self

    def __getattr__(self, _):
        return lambda *a, **k: self

    def execute(self):
        return self


def _score_one(monkeypatch, cluster, classification):
    import app.scorer as scorer
    log, calls = [], []

    class DB:
        def table(self, name):
            data = {"clusters": [cluster], "stories": [{"id": "s", "outlet_id": None, "summary": None}]}.get(name, [])
            return _Q(name, data, log)

    monkeypatch.setattr(scorer, "supabase", DB())
    monkeypatch.setattr(scorer, "classify_cluster", lambda *a: calls.append(a) or classification)
    scorer.run_scoring()
    updates = [p for name, p in log if name == "clusters" and "category" in p]
    return (updates[0] if updates else None), calls


BASE = {"id": "c1", "outlet_count": 2, "representative_title": "t", "category": None, "category_classified_at": None}


class TestScorerGating:
    def test_confident_answer_is_final_and_unflagged(self, monkeypatch):
        upd, _ = _score_one(monkeypatch, dict(BASE), {"category": "Politics", "confidence": 0.9, "retry": False})
        assert upd["category_classified_at"] and "monitoring_flags" not in upd

    def test_low_confidence_is_flagged_for_review(self, monkeypatch):
        upd, _ = _score_one(monkeypatch, dict(BASE), {"category": "Politics", "confidence": 0.6, "retry": False})
        assert "low_confidence_category" in upd["monitoring_flags"]

    def test_unusable_answer_is_flagged_and_not_retried(self, monkeypatch):
        upd, _ = _score_one(monkeypatch, dict(BASE), {"category": "General", "confidence": 0.0, "retry": False})
        assert "low_confidence_category" in upd["monitoring_flags"] and upd.get("category_classified_at")

    def test_failed_call_is_flagged_and_retried_next_cycle(self, monkeypatch):
        upd, _ = _score_one(monkeypatch, dict(BASE), {"category": "General", "confidence": 0.0, "retry": True})
        assert "low_confidence_category" in upd["monitoring_flags"] and "category_classified_at" not in upd

    def test_existing_flags_are_kept_when_flagging(self, monkeypatch):
        cluster = dict(BASE, monitoring_flags=[{"type": "COVERAGE_GAP"}])
        upd, _ = _score_one(monkeypatch, cluster, {"category": "Politics", "confidence": 0.5, "retry": False})
        assert upd["monitoring_flags"] == [{"type": "COVERAGE_GAP"}, "low_confidence_category"]

    def test_already_classified_cluster_is_never_reclassified(self, monkeypatch):
        cluster = dict(BASE, category="Politics", category_classified_at="2026-10-01T00:00:00+00:00")
        upd, calls = _score_one(monkeypatch, cluster, {"category": "Economy", "confidence": 0.9, "retry": False})
        assert calls == [] and upd is None
