import pytest
from app.monitoring_spirit import (
    resolve_verdict,
    is_significant,
    has_persistence,
    has_sourcing,
    TIER_GOVT,
    TIER_MAINSTREAM,
    TIER_WATCHDOG
)


class TestSignificanceRail:
    def test_accountability_category_fires(self):
        assert is_significant(
            "Politics", False, False
        ) == True

    def test_sport_category_does_not_fire(self):
        assert is_significant(
            "Sports", False, False
        ) == False

    def test_entity_tag_overrides_category(self):
        # A health story tagged with 
        # a politician should still 
        # be significant
        assert is_significant(
            "Health", True, False
        ) == True

    def test_money_figure_overrides_category(self):
        assert is_significant(
            "Entertainment", False, True
        ) == True

    def test_sport_with_no_tags_fails(self):
        # The England-Ghana false 
        # positive case
        assert is_significant(
            "Sports", False, False
        ) == False


class TestPersistenceRail:
    def make_reads(self, pattern):
        """
        pattern: list of (watch_pct, 
        govt_pct, total) tuples
        """
        reads = []
        for watch_pct, govt_pct, total \
                in pattern:
            reads.append({
                "tier_distribution": {
                    TIER_WATCHDOG: 
                        int(watch_pct * total),
                    TIER_GOVT: 
                        int(govt_pct * total),
                    TIER_MAINSTREAM: 
                        total - int(
                            watch_pct * total
                        ) - int(
                            govt_pct * total
                        )
                },
                "total": total
            })
        return reads

    def test_single_snapshot_fails(self):
        reads = self.make_reads([
            (0.8, 0.05, 10)
        ])
        assert has_persistence(
            reads, TIER_WATCHDOG, TIER_GOVT
        ) == False

    def test_two_consistent_snapshots_pass(self):
        reads = self.make_reads([
            (0.8, 0.05, 10),
            (0.75, 0.05, 8)
        ])
        assert has_persistence(
            reads, TIER_WATCHDOG, TIER_GOVT
        ) == True

    def test_breaking_news_artifact_fails(self):
        # First read shows imbalance 
        # (breaking story, coverage 
        # hasn't caught up), second 
        # read shows it resolved — 
        # this should NOT count as 
        # persistent
        reads = self.make_reads([
            (0.3, 0.3, 10),  # resolved
            (0.9, 0.0, 3)    # was imbalanced
        ])
        assert has_persistence(
            reads, TIER_WATCHDOG, TIER_GOVT
        ) == False

    def test_empty_reads_fails(self):
        assert has_persistence(
            [], TIER_WATCHDOG, TIER_GOVT
        ) == False


class TestSourcingRail:
    def test_single_source_fails(self):
        # The planted-leak guard
        assert has_sourcing({
            "distinct_outlets_in_loud_tier": 1,
            "has_original_reporting_outlet": True
        }) == False

    def test_multi_source_no_original_fails(self):
        assert has_sourcing({
            "distinct_outlets_in_loud_tier": 5,
            "has_original_reporting_outlet": False
        }) == False

    def test_multi_source_with_original_passes(self):
        assert has_sourcing({
            "distinct_outlets_in_loud_tier": 5,
            "has_original_reporting_outlet": True
        }) == True

    def test_exactly_three_sources_passes(self):
        assert has_sourcing({
            "distinct_outlets_in_loud_tier": 3,
            "has_original_reporting_outlet": True
        }) == True

    def test_two_sources_fails(self):
        assert has_sourcing({
            "distinct_outlets_in_loud_tier": 2,
            "has_original_reporting_outlet": True
        }) == False


class TestDirectionAgnosticSymmetry:
    """
    THE CRITICAL GATE A TEST.
    Confirms the engine produces 
    the SAME verdict structure for 
    BOTH directions — Watchdog-silent 
    and Govt-silent. This is the 
    test that would fail if the 
    self-monitoring symmetry broke.
    """

    def test_watchdog_loud_govt_silent_reaches_dark(self):
        snapshot_reads = [
            {
                "tier_distribution": {
                    TIER_WATCHDOG: 8,
                    TIER_GOVT: 0,
                    TIER_MAINSTREAM: 1
                },
                "total": 9
            },
            {
                "tier_distribution": {
                    TIER_WATCHDOG: 7,
                    TIER_GOVT: 0,
                    TIER_MAINSTREAM: 1
                },
                "total": 8
            }
        ]
        sourcing_info = {
            "distinct_outlets_in_loud_tier": 8,
            "has_original_reporting_outlet": True
        }
        result = resolve_verdict(
            tier_distribution={
                TIER_WATCHDOG: 8,
                TIER_GOVT: 0,
                TIER_MAINSTREAM: 1
            },
            total_outlets=9,
            category="Politics",
            snapshot_reads=snapshot_reads,
            sourcing_info=sourcing_info
        )
        assert result["verdict"] == "dark"
        assert len(result["evidence"]) > 0
        assert result["rails"]["persistence"] == True
        assert result["rails"]["sourcing"] == True

    def test_govt_loud_watchdog_silent_reaches_dark(self):
        """
        THE MIRROR CASE. Must reach 
        the same verdict structure 
        as the test above, with 
        roles reversed. If this 
        fails while the test above 
        passes, the engine has 
        hardcoded asymmetry and 
        Gate A does not pass.
        """
        snapshot_reads = [
            {
                "tier_distribution": {
                    TIER_GOVT: 8,
                    TIER_WATCHDOG: 0,
                    TIER_MAINSTREAM: 1
                },
                "total": 9
            },
            {
                "tier_distribution": {
                    TIER_GOVT: 7,
                    TIER_WATCHDOG: 0,
                    TIER_MAINSTREAM: 1
                },
                "total": 8
            }
        ]
        sourcing_info = {
            "distinct_outlets_in_loud_tier": 8,
            "has_original_reporting_outlet": True
        }
        result = resolve_verdict(
            tier_distribution={
                TIER_GOVT: 8,
                TIER_WATCHDOG: 0,
                TIER_MAINSTREAM: 1
            },
            total_outlets=9,
            category="Politics",
            snapshot_reads=snapshot_reads,
            sourcing_info=sourcing_info
        )
        assert result["verdict"] == "dark"
        assert len(result["evidence"]) > 0
        assert result["rails"]["persistence"] == True
        assert result["rails"]["sourcing"] == True

    def test_symmetry_evidence_language_matches_direction(self):
        """
        Confirms the evidence string 
        correctly names WHICH tier 
        is silent in each direction 
        — not hardcoded to always 
        say "government."
        """
        snapshot_reads = [
            {"tier_distribution": {
                TIER_WATCHDOG: 8, 
                TIER_GOVT: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 9},
            {"tier_distribution": {
                TIER_WATCHDOG: 7, 
                TIER_GOVT: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 8}
        ]
        sourcing_info = {
            "distinct_outlets_in_loud_tier": 8,
            "has_original_reporting_outlet": True
        }
        watchdog_loud = resolve_verdict(
            tier_distribution={
                TIER_WATCHDOG: 8,
                TIER_GOVT: 0,
                TIER_MAINSTREAM: 1
            },
            total_outlets=9,
            category="Politics",
            snapshot_reads=snapshot_reads,
            sourcing_info=sourcing_info
        )
        govt_loud_reads = [
            {"tier_distribution": {
                TIER_GOVT: 8, 
                TIER_WATCHDOG: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 9},
            {"tier_distribution": {
                TIER_GOVT: 7, 
                TIER_WATCHDOG: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 8}
        ]
        govt_loud = resolve_verdict(
            tier_distribution={
                TIER_GOVT: 8,
                TIER_WATCHDOG: 0,
                TIER_MAINSTREAM: 1
            },
            total_outlets=9,
            category="Politics",
            snapshot_reads=govt_loud_reads,
            sourcing_info=sourcing_info
        )
        
        watchdog_evidence_text = " ".join(
            e["detail"] for e in 
            watchdog_loud["evidence"]
        )
        govt_evidence_text = " ".join(
            e["detail"] for e in 
            govt_loud["evidence"]
        )
        
        # When watchdog is loud, the 
        # silence evidence should 
        # name "government-aligned"
        assert "government-aligned" in \
            watchdog_evidence_text
        # When govt is loud, the 
        # silence evidence should 
        # name "watchdog"
        assert "watchdog" in \
            govt_evidence_text

    def test_persistence_without_sourcing_caps_at_mixed_both_directions(self):
        """
        Single-source planted-leak 
        guard must work identically 
        in both directions.
        """
        single_source_sourcing = {
            "distinct_outlets_in_loud_tier": 1,
            "has_original_reporting_outlet": True
        }
        snapshot_reads = [
            {"tier_distribution": {
                TIER_WATCHDOG: 8, 
                TIER_GOVT: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 9},
            {"tier_distribution": {
                TIER_WATCHDOG: 7, 
                TIER_GOVT: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 8}
        ]
        watchdog_result = resolve_verdict(
            tier_distribution={
                TIER_WATCHDOG: 8,
                TIER_GOVT: 0,
                TIER_MAINSTREAM: 1
            },
            total_outlets=9,
            category="Politics",
            snapshot_reads=snapshot_reads,
            sourcing_info=single_source_sourcing
        )
        assert watchdog_result["verdict"] \
            == "mixed"
        
        govt_reads = [
            {"tier_distribution": {
                TIER_GOVT: 8, 
                TIER_WATCHDOG: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 9},
            {"tier_distribution": {
                TIER_GOVT: 7, 
                TIER_WATCHDOG: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 8}
        ]
        govt_result = resolve_verdict(
            tier_distribution={
                TIER_GOVT: 8,
                TIER_WATCHDOG: 0,
                TIER_MAINSTREAM: 1
            },
            total_outlets=9,
            category="Politics",
            snapshot_reads=govt_reads,
            sourcing_info=single_source_sourcing
        )
        assert govt_result["verdict"] \
            == "mixed"


class TestCalmStateLoadBearing:
    """
    DARK requires CLEAR to exist and 
    fire correctly — the brief states 
    CLEAR is load-bearing and must 
    not be deprioritized.
    """

    def test_broad_balanced_coverage_is_clear(self):
        result = resolve_verdict(
            tier_distribution={
                TIER_GOVT: 3,
                TIER_MAINSTREAM: 4,
                TIER_WATCHDOG: 3
            },
            total_outlets=10,
            category="Politics",
            churnalism_ratio=0.2
        )
        assert result["verdict"] == "clear"
        assert result["verdict_line"] == \
            "Covered widely, across outlet types"

    def test_clear_has_evidence_when_broad(self):
        result = resolve_verdict(
            tier_distribution={
                TIER_GOVT: 3,
                TIER_MAINSTREAM: 4,
                TIER_WATCHDOG: 3
            },
            total_outlets=10,
            category="Politics",
            churnalism_ratio=0.2
        )
        assert len(result["evidence"]) > 0


class TestChurnalismInFindingsNotGate:
    """
    Confirms churnalism contributes 
    to MIXED/DARK findings rather 
    than gating significance — per 
    the lead's correction.
    """

    def test_high_churnalism_alone_is_mixed(self):
        result = resolve_verdict(
            tier_distribution={
                TIER_GOVT: 2,
                TIER_MAINSTREAM: 6,
                TIER_WATCHDOG: 2
            },
            total_outlets=10,
            category="Politics",
            churnalism_ratio=0.7
        )
        assert result["verdict"] == "mixed"

    def test_low_churnalism_does_not_force_mixed(self):
        result = resolve_verdict(
            tier_distribution={
                TIER_GOVT: 3,
                TIER_MAINSTREAM: 4,
                TIER_WATCHDOG: 3
            },
            total_outlets=10,
            category="Politics",
            churnalism_ratio=0.1
        )
        assert result["verdict"] == "clear"


class TestSportFalsePositiveGuard:
    """
    The England-Ghana football case 
    that broke the legacy system.
    """

    def test_sport_silence_does_not_reach_dark(self):
        snapshot_reads = [
            {"tier_distribution": {
                TIER_WATCHDOG: 8, 
                TIER_GOVT: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 9},
            {"tier_distribution": {
                TIER_WATCHDOG: 7, 
                TIER_GOVT: 0, 
                TIER_MAINSTREAM: 1
            }, "total": 8}
        ]
        sourcing_info = {
            "distinct_outlets_in_loud_tier": 8,
            "has_original_reporting_outlet": True
        }
        result = resolve_verdict(
            tier_distribution={
                TIER_WATCHDOG: 8,
                TIER_GOVT: 0,
                TIER_MAINSTREAM: 1
            },
            total_outlets=9,
            category="Sports",
            has_entity_tag=False,
            has_money_figure=False,
            snapshot_reads=snapshot_reads,
            sourcing_info=sourcing_info
        )
        assert result["verdict"] != "dark"
        assert result["rails"]["significance"] \
            == False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
