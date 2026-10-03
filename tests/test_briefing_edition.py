"""Rebuilt Daily Briefing rules (counsel, 3 Oct 2026, section B)."""
import pytest

import app.briefing_edition as be
from app import briefingStrings


def cluster(cid, distinct, seen="2026-10-03T05:00:00Z", image=True):
    return {"id": cid, "slug": cid, "first_seen_at": seen,
            "coverage_stats": {"coverage_tier_distribution": {"govt_aligned": 0, "mainstream": distinct, "watchdog": 0}},
            "stories": [{"image_url": "https://img/x.jpg" if image else None}]}


def test_selection_is_by_breadth_then_recency_never_tier():
    picked = be.select_clusters([cluster("narrow", 5), cluster("wide", 9), cluster("wide-newer", 9, seen="2026-10-03T06:00:00Z"),
                                 cluster("too-few", 4), cluster("no-image", 12, image=False)])
    assert [c["id"] for c in picked] == ["wide-newer", "wide", "narrow"]


def summary(gate, published=None, flags=None, bullets=("A thing happened.", "Officials said so.")):
    return {"id": "s1", "gate": gate, "published": gate == "auto" if published is None else published,
            "flags": flags, "bullets": list(bullets)}


@pytest.mark.parametrize("gate,approved,expected", [
    ("auto", None, True),
    ("review", None, False), ("review", "Editor (editorial)", True),
    ("senior_review", None, False), ("senior_review", "Editor (super_admin)", True),
    ("suppress", "Editor (editorial)", False),
])
def test_publish_rule(gate, approved, expected):
    assert be.is_publishable({"approved_by": approved}, summary(gate)) is expected


def test_flagged_or_forbidden_never_publishes():
    assert not be.is_publishable({"approved_by": "E"}, summary("review", flags=["escalation: charged"]))
    assert not be.is_publishable({}, summary("auto", bullets=("The two sides disagreed.", "x")))
    assert not be.is_publishable({}, summary("auto", bullets=("Turnout was 40%.", "x")))
    assert not be.is_publishable({}, {**summary("auto"), "superseded": True})


def test_ui_strings_carry_no_forbidden_token_and_the_required_labels():
    texts = [v for v in briefingStrings.UI.values() if isinstance(v, str)] + list(briefingStrings.UI["tier_labels"].values())
    assert be.has_forbidden_token(texts) is None
    assert briefingStrings.UI["attribution_label"] == "AI-generated summary of the sources"


def test_summary_model_receives_no_outlet_identifier(monkeypatch):
    import app.summarizer as summarizer
    sent = {}

    class Rows:
        data = [{"title": "Headline one", "summary": "Text one"}, {"title": "Headline two", "summary": "Text two"}]

    class Q:
        def __getattr__(self, _):
            return lambda *a, **k: self

        def execute(self):
            return Rows()

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kw):
                    sent["messages"] = kw["messages"]
                    raise RuntimeError("stop after capturing the prompt")

    monkeypatch.setattr(summarizer, "supabase", type("DB", (), {"table": lambda self, t: Q()})())
    monkeypatch.setattr(summarizer, "openai_client", Client)
    monkeypatch.setattr(summarizer, "record_generation_failure", lambda *a: None)
    summarizer.generate_cluster_summary("c1")
    articles = sent["messages"][1]["content"].split("covering this story:")[1].split("Write ")[0]
    assert articles.strip().splitlines()[0] == "Source 1"
    assert "Source 2" in articles and "Source:" not in articles and "outlet" not in articles.lower()
