"""The staff verdict list counts tiers from the stories' outlet ids."""
import app.routers.monitoring_spirit_admin as msa


class Q:
    def __init__(self, rows): self.rows = rows
    def __getattr__(self, _): return lambda *a, **k: self
    def execute(self): return type("R", (), {"data": self.rows})()


def test_verdict_list_matches_stories_to_outlets_by_id(monkeypatch):
    clusters = [{"id": "c1", "slug": "s", "representative_title": "T", "created_at": "2026-10-04T00:00:00Z",
                 "category": "Politics", "coverage_stats": {}}]
    stories = [{"cluster_id": "c1", "outlet_id": f"o{i}", "story_bias_tags": []} for i in range(6)]
    tables = {"clusters": clusters, "verdict_overrides": [], "stories": stories, "coverage_snapshots": []}
    monkeypatch.setattr(msa, "supabase", type("DB", (), {"table": lambda self, t: Q(tables[t])})())
    outlets = {f"o{i}": {"id": f"o{i}", "slug": f"out{i}", "government_alignment": "pro_government", "is_blog": False}
               for i in range(6)}
    monkeypatch.setattr(msa, "_get_outlets_cache", lambda: (outlets, {}))
    seen = {}
    real = msa.resolve_verdict

    def spy(**kw):
        seen.update(kw)
        return real(**kw)
    monkeypatch.setattr(msa, "resolve_verdict", spy)
    msa.list_current_verdicts("bypass")
    assert seen["total_outlets"] == 6 and sum(seen["tier_distribution"].values()) == 6


def test_outlet_map_is_keyed_by_outlet_id(monkeypatch):
    import app.coverage as cov
    rows = {"outlets": [{"id": "o1", "slug": "punch", "government_alignment": "neutral", "is_blog": False}],
            "outlet_behavioral_scores": [{"outlet_slug": "punch", "s2_score": 60}]}
    monkeypatch.setattr(cov, "supabase", type("DB", (), {"table": lambda self, t: Q(rows[t])})())
    monkeypatch.setattr(cov, "_OUTLETS_CACHE", {})
    monkeypatch.setattr(cov, "_LAST_CACHE_UPDATE", 0)
    outlets, behavioural = msa._get_outlets_cache()
    assert "o1" in outlets and "punch" not in outlets
    assert "punch" in behavioural
