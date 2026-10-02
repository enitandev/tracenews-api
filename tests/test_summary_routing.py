"""
Legal-risk routing for event summaries (app.summarizer.evaluate_summary)
and what the reader endpoint serves for each outcome.
"""
from app.summarizer import evaluate_summary
from app.storySummaryStrings import (
    GATE_AUTO_PUBLISH, GATE_HUMAN_REVIEW, GATE_SUPPRESS_CLAIM, GATE_SENIOR_REVIEW,
)

SOURCES = "Headline: Senate passes budget\nSummary: The Senate passed the 2027 budget on Tuesday."


def evaluate(bullets, sources=SOURCES):
    return evaluate_summary(bullets, sources)


class TestGate:
    def test_neutral_bullets_auto_publish(self):
        r = evaluate(["The Senate passed the 2027 budget.", "The vote was held on Tuesday."])
        assert r["gate"] == GATE_AUTO_PUBLISH and r["flags"] == [] and r["published"] is True

    def test_adverse_claim_without_anchor_is_suppressed(self):
        r = evaluate(["A commissioner was accused of fraud.", "He has not commented."])
        assert r["gate"] == GATE_SUPPRESS_CLAIM and r["published"] is False

    def test_adverse_claim_with_public_record_anchor_goes_to_review(self):
        r = evaluate(["A commissioner faces fraud allegations in a suit filed in court.", "He denies them."])
        assert r["gate"] == GATE_HUMAN_REVIEW and r["published"] is False

    def test_adverse_claim_naming_a_principal_goes_to_senior_review(self):
        r = evaluate(["Critics alleged that Tinubu's aides diverted funds.", "The Presidency has not responded."])
        assert r["gate"] == GATE_SENIOR_REVIEW and r["published"] is False

    def test_principal_beats_anchor(self):
        # Even with a court anchor, naming a principal officeholder escalates to senior review.
        r = evaluate(["A suit filed in court alleges that Akpabio misused funds.", "Hearing is set for May."])
        assert r["gate"] == GATE_SENIOR_REVIEW

    def test_office_title_alone_counts_as_principal(self):
        r = evaluate(["The Chief Justice was accused of bias.", "The NJC is reviewing."])
        assert r["gate"] == GATE_SENIOR_REVIEW

    def test_matching_is_case_insensitive_and_whole_word(self):
        assert evaluate(["ALLEGED misconduct was reported.", "x y z."])["gate"] == GATE_SUPPRESS_CLAIM
        # 'fraudster' is not the listed term 'fraud'; 'accusatory' is not 'accuse'.
        assert evaluate(["An accusatory tone marked the debate.", "Fraudsters were discussed in general."])["gate"] == GATE_AUTO_PUBLISH


class TestFlags:
    def test_escalation_term_not_in_sources_blocks_publication(self):
        r = evaluate(["The minister was charged over the budget.", "The Senate met."])
        assert "escalation: charged" in r["flags"] and r["published"] is False

    def test_escalation_term_present_in_sources_is_not_an_escalation(self):
        sources = SOURCES + "\nSummary: The minister was charged by the EFCC."
        r = evaluate(["The minister was charged.", "The Senate met."], sources)
        assert not any(f.startswith("escalation") for f in r["flags"])

    def test_coverage_language_blocks_publication(self):
        r = evaluate(["Most outlets downplayed the vote.", "The Senate met."])
        assert "forbidden_coverage: outlets" in r["flags"] and "forbidden_coverage: downplayed" in r["flags"]
        assert r["published"] is False

    def test_bullet_count_outside_two_to_five_blocks_publication(self):
        assert "bullet_count: 1" in evaluate(["Only one."])["flags"]
        assert "bullet_count: 6" in evaluate([f"Point {i}." for i in range(6)])["flags"]
        assert evaluate(["Only one."])["published"] is False

    def test_non_text_bullet_is_flagged_not_coerced(self):
        r = evaluate([{"text": "The Senate met."}, "The vote passed."])
        assert any(f.startswith("bullet_type") for f in r["flags"]) and r["published"] is False

    def test_flag_blocks_publication_even_with_auto_gate(self):
        r = evaluate(["The coverage was wide.", "The Senate met."])
        assert r["gate"] == GATE_AUTO_PUBLISH and r["published"] is False


class TestServedSummary:
    def _serve(self, monkeypatch, row):
        import app.routers.story as story

        class Q:
            data = [row] if row else []

            def __getattr__(self, _):
                return lambda *a, **k: self

            def execute(self):
                return self

        class DB:
            def table(self, _):
                return Q()

        monkeypatch.setattr(story, "supabase", DB())
        return story.get_cluster_summary("c1")

    def test_published_summary_serves_bullets(self, monkeypatch):
        r = self._serve(monkeypatch, {"published": True, "gate": "auto", "bullets": ["a", "b"]})
        assert r["status"] == "published" and r["bullets"] == ["a", "b"]

    def test_gated_summaries_never_serve_bullets(self, monkeypatch):
        for gate in (GATE_HUMAN_REVIEW, GATE_SUPPRESS_CLAIM, GATE_SENIOR_REVIEW):
            r = self._serve(monkeypatch, {"published": False, "gate": gate, "bullets": ["secret claim"], "flags": None})
            assert r["bullets"] == [], gate

    def test_flagged_auto_summary_never_serves_bullets(self, monkeypatch):
        r = self._serve(monkeypatch, {"published": False, "gate": "auto", "bullets": ["x"], "flags": ["escalation: charged"]})
        assert r["bullets"] == [] and r["status"] == "withheld"
