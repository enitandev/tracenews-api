from app.tier_utils import count_outlet_tiers, card_distribution
from app.scorer import coverage_gap_flag, unverified_viral_flag


def outlet(oid, alignment=None, is_blog=False, **extra):
    return {"id": oid, "slug": oid, "government_alignment": alignment, "is_blog": is_blog, **extra}


class TestCountOutletTiers:
    def test_counts_each_outlet_once(self):
        a = outlet("a", "opposition")
        counts = count_outlet_tiers([a, a, a, outlet("b", "neutral")])
        assert card_distribution(counts) == {"govt_aligned": 0, "mainstream": 1, "watchdog": 1}

    def test_all_keys_present_even_when_zero(self):
        counts = count_outlet_tiers([])
        assert counts == {"govt_aligned": 0, "mainstream": 0, "watchdog": 0, "blog": 0, "unscored": 0}

    def test_unrecognised_and_missing_alignment_are_unscored_not_a_tier(self):
        counts = count_outlet_tiers([outlet("a", "Institutional"), outlet("b", None)])
        assert counts["unscored"] == 2
        assert sum(card_distribution(counts).values()) == 0

    def test_blogs_counted_separately(self):
        counts = count_outlet_tiers([outlet("a", "pro_government", is_blog=True)])
        assert counts["blog"] == 1 and counts["govt_aligned"] == 0


class TestCoverageGapFlag:
    def test_names_only_missing_regions(self):
        flag = coverage_gap_flag({"North": 2, "Southwest": 3}, 5)
        assert flag["message"] == "No regional publications from the Southeast or South-South have picked this story up."

    def test_single_missing_region(self):
        flag = coverage_gap_flag({"North": 1, "Southwest": 1, "Southeast": 3}, 5)
        assert "from the South-South have" in flag["message"]
        assert "North" not in flag["message"]

    def test_no_flag_when_all_or_none_covered(self):
        assert coverage_gap_flag({r: 1 for r in ["North", "Southwest", "Southeast", "South-South"]}, 6) is None
        assert coverage_gap_flag({}, 6) is None

    def test_no_flag_below_five_outlets(self):
        assert coverage_gap_flag({"North": 2}, 4) is None


class TestUnverifiedViralFlag:
    def test_fires_only_when_every_outlet_is_a_blog(self):
        counts = count_outlet_tiers([outlet(x, is_blog=True) for x in "abc"])
        assert unverified_viral_flag(counts)["type"] == "UNVERIFIED_VIRAL"

    def test_one_tiered_outlet_suppresses_it(self):
        counts = count_outlet_tiers([outlet(x, is_blog=True) for x in "abc"] + [outlet("d", "neutral")])
        assert unverified_viral_flag(counts) is None

    def test_unscored_outlet_suppresses_it(self):
        counts = count_outlet_tiers([outlet(x, is_blog=True) for x in "abc"] + [outlet("d", None)])
        assert unverified_viral_flag(counts) is None


class _Recorder:
    def __init__(self, tables, log):
        self.tables, self.log = tables, log

    def table(self, name):
        return _Query(name, self.tables.get(name, []), self.log)


class _Query:
    def __init__(self, name, data, log):
        self.name, self.data, self.log = name, data, log

    def update(self, payload):
        self.log.append(("update", self.name, payload))
        return self

    def insert(self, payload):
        self.log.append(("insert", self.name, payload))
        return self

    def __getattr__(self, _name):
        return lambda *args, **kwargs: self

    def execute(self):
        return self


def test_scorer_writes_distinct_outlet_counts_with_every_tier(monkeypatch):
    import app.scorer as scorer
    outlets = [
        outlet("o1", "opposition", geopolitical_lean="North", independence_score=80),
        outlet("o2", "neutral"),
    ]
    # o1 published three articles; o2 one.
    stories = [{"id": f"s{i}", "outlet_id": oid, "outlet_slug": oid, "summary": ""}
               for i, oid in enumerate(["o1", "o1", "o1", "o2"])]
    log = []
    monkeypatch.setattr(scorer, "supabase", _Recorder({
        "clusters": [{"id": "c1", "outlet_count": 4, "category": "Politics",
                      "representative_title": "t", "category_classified_at": "2026-10-01"}],
        "stories": stories,
        "outlets": outlets,
        "outlet_behavioral_scores": [],
        "coverage_snapshots": [],
    }, log))

    scorer.run_scoring()

    stats = next(p for op, t, p in log if op == "update" and t == "clusters" and "coverage_stats" in p)["coverage_stats"]
    assert stats["coverage_tier_distribution"] == {"govt_aligned": 0, "mainstream": 1, "watchdog": 1}
    assert stats["total_coverage"] == 2
    assert stats["geopolitical_distribution"] == {"North": 1}
    assert stats["ownership_distribution"] == {}
    assert stats["average_independence_score"] == 80
    assert "credibility_distribution" not in stats

    snap = next(p for op, t, p in log if op == "insert" and t == "coverage_snapshots")
    assert snap["coverage_tier_distribution"] == {"govt_aligned": 0, "mainstream": 1, "watchdog": 1}
    assert snap["outlet_count"] == 2
