from app.main import render_safe_verdict
from app.tier_utils import is_republisher, normalize_tier_distribution


class TestRenderSafeVerdict:
    def test_dark_is_withheld_not_relabelled(self):
        assert render_safe_verdict({"verdict": "dark", "evidence": [{"type": "silence"}]}) is None

    def test_clear_and_mixed_pass_through(self):
        for state in ("clear", "mixed"):
            payload = {"verdict": state, "evidence": []}
            assert render_safe_verdict(payload) is payload


class TestNormalizeTierDistribution:
    def test_canonical_keys_fill_absent_tiers_with_zero(self):
        assert normalize_tier_distribution({"watchdog": 4}) == {
            "govt_aligned": 0, "mainstream": 0, "watchdog": 4
        }

    def test_legacy_keys_map_to_canonical(self):
        assert normalize_tier_distribution(
            {"pro_establishment": 2, "institutional": 5, "adversarial": 1}
        ) == {"govt_aligned": 2, "mainstream": 5, "watchdog": 1}

    def test_blog_and_unscored_are_dropped(self):
        assert normalize_tier_distribution({"mainstream": 3, "blog": 2, "unscored": 1}) == {
            "govt_aligned": 0, "mainstream": 3, "watchdog": 0
        }

    def test_unrecognised_key_makes_distribution_unusable(self):
        assert normalize_tier_distribution({"mainstream": 3, "Institutional": 2}) is None

    def test_missing_distribution_is_unusable_not_zero(self):
        assert normalize_tier_distribution(None) is None


class TestIsRepublisher:
    def test_bands(self):
        assert is_republisher(None) is None
        assert is_republisher(10) is True
        assert is_republisher(39.9) is True
        assert is_republisher(40) is None
        assert is_republisher(49) is None
        assert is_republisher(50) is False
        assert is_republisher(90) is False


class _FakeQuery:
    def __init__(self, data):
        self.data = data

    def __getattr__(self, _name):
        return lambda *args, **kwargs: self

    def execute(self):
        return self


class _FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _FakeQuery(self.tables[name])


def _by_slug_with_verdict(monkeypatch, verdict_result, snapshots):
    import app.main as main
    outlets = {
        "o1": {"id": "o1", "slug": "a", "government_alignment": "opposition", "is_blog": False},
        "o2": {"id": "o2", "slug": "b", "government_alignment": "opposition", "is_blog": False},
    }
    stories = [
        {"id": "s1", "outlet_id": "o1", "story_bias_tags": [],
         "outlets": {"slug": "a", "name": "A", "government_alignment": "opposition", "is_blog": False}},
        {"id": "s2", "outlet_id": "o2", "story_bias_tags": [],
         "outlets": {"slug": "b", "name": "B", "government_alignment": "opposition", "is_blog": False}},
    ]
    monkeypatch.setattr(main, "supabase", _FakeSupabase({
        "clusters": [{"id": "c1", "slug": "x", "category": "Politics", "coverage_stats": {}}],
        "stories": stories,
        "coverage_snapshots": snapshots,
    }))
    monkeypatch.setattr(main, "get_outlets_cache", lambda: (outlets, {"a": {"s2_score": 20}}))
    monkeypatch.setattr(main, "resolve_verdict", lambda **kwargs: verdict_result)
    return main.get_cluster_by_slug("x")


def test_forced_dark_never_reaches_the_payload(monkeypatch):
    res = _by_slug_with_verdict(monkeypatch, {"verdict": "dark", "evidence": [{"type": "silence"}]}, [])
    assert "monitoring_spirit_live" not in res["cluster"]


def test_payload_snapshots_are_normalised_and_unusable_rows_dropped(monkeypatch):
    snaps = [
        {"snapshot_at": "2026-10-01T10:00:00Z", "coverage_tier_distribution": {"watchdog": 2}},
        {"snapshot_at": "2026-10-01T09:00:00Z", "coverage_tier_distribution": {"adversarial": 1}},
        {"snapshot_at": "2026-10-01T08:00:00Z", "coverage_tier_distribution": None},
    ]
    res = _by_slug_with_verdict(monkeypatch, {"verdict": "mixed", "evidence": []}, snaps)
    live = res["cluster"]["monitoring_spirit_live"]
    assert [s["coverage_tier_distribution"] for s in live["snapshots"]] == [
        {"govt_aligned": 0, "mainstream": 0, "watchdog": 2},
        {"govt_aligned": 0, "mainstream": 0, "watchdog": 1},
    ]
    by_id = {s["id"]: s for s in res["stories"]}
    assert by_id["s1"]["outlet_republishes"] is True
    assert by_id["s2"]["outlet_republishes"] is None
