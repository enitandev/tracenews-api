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

    def test_bullet_count_outside_two_to_eight_blocks_publication(self):
        # Counsel, 3 Oct 2026: up to 8 points.
        assert "bullet_count: 1" in evaluate(["Only one."])["flags"]
        assert not any(f.startswith("bullet_count") for f in evaluate([f"Point {i}." for i in range(8)])["flags"])
        assert "bullet_count: 9" in evaluate([f"Point {i}." for i in range(9)])["flags"]
        assert evaluate(["Only one."])["published"] is False

    # Counsel, 3 Oct 2026: harm events are split from conduct.
    def test_harm_event_alone_with_no_named_person_publishes(self):
        r = evaluate(["Troops killed 16 insurgents in Adamawa, according to a military statement.",
                      "Three soldiers died in the attacks, the army said."])
        assert r["gate"] == "auto" and r["published"] is True

    def test_harm_event_never_suppresses(self):
        r = evaluate(["A flood killed 12 people in Mokwa.", "Rescue work continued."])
        assert r["gate"] != "suppress"

    def test_harm_event_naming_a_person_goes_to_review(self):
        r = evaluate(["Gunmen killed Musa Bello, a farmer, in Kaduna, the police said.", "Residents fled."])
        assert r["gate"] == "review"

    def test_harm_event_with_a_conduct_term_keeps_the_conduct_treatment(self):
        r = evaluate(["Soldiers killed 4 people; the army alleged the protesters were armed.", "Residents fled."])
        assert r["gate"] == "suppress"

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


class TestServedSummaryLifecycle(TestServedSummary):
    def test_superseded_summary_is_not_served(self, monkeypatch):
        r = self._serve(monkeypatch, {"published": True, "gate": "auto", "bullets": ["old"], "superseded": True})
        assert r["status"] == "pending" and r["bullets"] == []

    def test_generation_failure_row_reads_as_error(self, monkeypatch):
        r = self._serve(monkeypatch, {"published": False, "gate": "review", "bullets": [], "flags": ["generation_failed: Timeout"]})
        assert r["status"] == "error" and r["bullets"] == []


FAIL = {"flags": ["generation_failed: RuntimeError"]}


class TestSummaryRetryCap:
    def needing(self, rows_by_cluster):
        from app.worker import clusters_needing_summary
        rows = [dict(r, cluster_id=cid) for cid, rs in rows_by_cluster.items() for r in rs]
        return clusters_needing_summary(list(rows_by_cluster), rows)

    def test_new_cluster_is_summarised(self):
        assert self.needing({"a": []}) == ["a"]

    def test_existing_good_summary_is_left_alone(self):
        assert self.needing({"a": [{"flags": None}]}) == []

    def test_superseded_summary_is_regenerated(self):
        assert self.needing({"a": [{"superseded": True}]}) == ["a"]

    def test_failures_are_retried_up_to_the_cap(self):
        assert self.needing({"a": [FAIL]}) == ["a"]
        assert self.needing({"a": [FAIL, FAIL]}) == ["a"]
        assert self.needing({"a": [FAIL, FAIL, FAIL]}) == []

    def test_failure_count_resets_after_a_correction(self):
        # Newest first: one failure since the superseded summary.
        assert self.needing({"a": [FAIL, {"superseded": True}, FAIL, FAIL, FAIL]}) == ["a"]


def test_failed_generation_is_recorded_once(monkeypatch):
    import app.summarizer as summarizer
    inserts = []

    class Q:
        def __init__(self, name):
            self.name = name
            self.data = [{"title": "t", "summary": "s", "outlet_id": "o1"}, {"title": "t2", "summary": "s2", "outlet_id": "o2"}]

        def insert(self, payload):
            inserts.append((self.name, payload))
            return self

        def __getattr__(self, _):
            return lambda *a, **k: self

        def execute(self):
            return self

    class DB:
        def table(self, name):
            return Q(name)

    def fail(**kwargs):
        raise RuntimeError("model down")

    monkeypatch.setattr(summarizer, "supabase", DB())
    monkeypatch.setattr(summarizer.openai_client.chat.completions, "create", fail)
    assert summarizer.generate_cluster_summary("c1") is None
    assert len(inserts) == 1
    table, row = inserts[0]
    assert table == "cluster_summaries" and row["published"] is False and row["bullets"] == []
    assert row["flags"] == ["generation_failed: RuntimeError"]
