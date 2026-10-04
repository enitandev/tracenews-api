import pytest
from fastapi import HTTPException

from app.routers import briefing


@pytest.mark.parametrize("call", [lambda: briefing.get_daily_briefing(), lambda: briefing.get_daily_briefing_story("any")])
def test_briefing_endpoints_return_404_while_off(call, monkeypatch):
    monkeypatch.setattr(briefing, "BRIEFING_PUBLIC", False)
    with pytest.raises(HTTPException) as e:
        call()
    assert e.value.status_code == 404


def test_public_edition_is_cached_and_refreshed_in_the_background(monkeypatch):
    from datetime import date
    calls = []
    items = [{"slug": "a", "title": "A", "image_url": None, "category": "General", "coverage_counts": {}, "bullets": ["x"]},
             {"slug": "b", "title": "B", "image_url": None, "category": "General", "coverage_counts": {}, "bullets": ["y"]}]

    class Q:
        def __getattr__(self, _): return lambda *a, **k: self
        def execute(self): return type("R", (), {"data": [{"date": "2026-10-04"}]})()

    class InlineThread:                     # run background refreshes immediately in the test
        def __init__(self, target, daemon): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(briefing.threading, "Thread", InlineThread)
    monkeypatch.setattr(briefing, "BRIEFING_PUBLIC", True)
    monkeypatch.setattr(briefing, "supabase", type("DB", (), {"table": lambda self, t: Q()})())
    monkeypatch.setattr(briefing, "lagos_today", lambda: date(2026, 10, 4))
    monkeypatch.setattr(briefing, "edition_items", lambda day: calls.append(day) or items)
    monkeypatch.setattr(briefing, "_public", {"at": 0.0, "day": None, "items": [], "loaded": False})
    assert [i["slug"] for i in briefing.get_daily_briefing()["items"]] == ["a", "b"]
    story = briefing.get_daily_briefing_story("a")
    assert story["item"]["slug"] == "a" and [m["slug"] for m in story["more"]] == ["b"]
    assert "bullets" not in story["more"][0]
    assert len(calls) == 1                      # the second request was served from the cache
    briefing.clear_public_cache()               # an editor action refreshes the copy
    assert len(calls) == 2
    briefing._public["at"] = 0.0                # an expired copy is served, then refreshed
    briefing.get_daily_briefing()
    assert len(calls) == 3
