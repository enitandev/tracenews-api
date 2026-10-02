import logging
from app.tier_utils import get_outlet_tier, get_distinct_scored_count


class TestGetOutletTier:
    # Real outlet records (scripts/outlets.json) carry these alignment values.
    def test_live_values_map_exactly(self):
        assert get_outlet_tier("pro_government") == "govt_aligned"
        assert get_outlet_tier("neutral") == "mainstream"
        assert get_outlet_tier("opposition") == "watchdog"

    def test_case_insensitive(self):
        assert get_outlet_tier("Pro_Government") == "govt_aligned"

    def test_blog_wins_over_alignment(self):
        assert get_outlet_tier("opposition", is_blog=True) == "blog"

    def test_no_value_is_unscored(self):
        assert get_outlet_tier(None) == "unscored"
        assert get_outlet_tier("") == "unscored"

    def test_unrecognised_value_is_logged_and_unscored(self, caplog):
        with caplog.at_level(logging.ERROR, logger="app.tier_utils"):
            assert get_outlet_tier("Institutional") == "unscored"
        assert "Unrecognised government_alignment value: Institutional" in caplog.text

    def test_dead_credibility_tier_values_never_map_to_a_tier(self):
        for dead in ("Institutional", "Pro-Establishment", "Adversarial", "Sensational/Gist"):
            assert get_outlet_tier(dead) == "unscored"

    def test_every_seed_outlet_maps_to_a_card_tier(self):
        import json, pathlib
        outlets = json.loads((pathlib.Path(__file__).parent.parent / "scripts" / "outlets.json").read_text())
        tiers = {get_outlet_tier(o.get("government_alignment"), o.get("is_blog")) for o in outlets}
        assert tiers <= {"govt_aligned", "mainstream", "watchdog"}


class TestGetDistinctScoredCount:
    def test_sums_the_three_card_tiers(self):
        stats = {"coverage_tier_distribution": {"govt_aligned": 2, "mainstream": 3, "watchdog": 1}}
        assert get_distinct_scored_count(stats) == 6

    def test_blog_and_unscored_are_not_scored(self):
        stats = {"coverage_tier_distribution": {"mainstream": 3, "blog": 4, "unscored": 2}}
        assert get_distinct_scored_count(stats) == 3

    def test_no_value_is_none_not_zero(self):
        assert get_distinct_scored_count(None) is None
        assert get_distinct_scored_count({}) is None
        assert get_distinct_scored_count({"coverage_tier_distribution": None}) is None
        assert get_distinct_scored_count({"coverage_tier_distribution": {}}) is None

    def test_legacy_keys_are_counted_not_read_as_zero(self):
        stats = {"coverage_tier_distribution": {"pro_establishment": 1, "institutional": 2, "adversarial": 3}}
        assert get_distinct_scored_count(stats) == 6

    def test_unrecognised_key_is_unknown_not_zero(self):
        stats = {"coverage_tier_distribution": {"Institutional": 5}}
        assert get_distinct_scored_count(stats) is None

    def test_explicit_zero_is_zero(self):
        stats = {"coverage_tier_distribution": {"govt_aligned": 0, "mainstream": 0, "watchdog": 0}}
        assert get_distinct_scored_count(stats) == 0
