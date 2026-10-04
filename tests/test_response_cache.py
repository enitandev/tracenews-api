import threading

from app import response_cache as rc


class InlineThread:
    def __init__(self, target, args=(), daemon=True): self.target, self.args = target, args
    def start(self): self.target(*self.args)


def test_served_from_cache_then_refreshed_in_the_background(monkeypatch):
    rc.clear()
    clock = [1000.0]
    monkeypatch.setattr(rc.time, "time", lambda: clock[0])
    monkeypatch.setattr(rc.threading, "Thread", InlineThread)
    calls = []

    @rc.cached_response(ttl=90)
    def landing(limit=15):
        calls.append(limit)
        return {"clusters": [len(calls)]}

    assert landing(limit=15) == {"clusters": [1]}
    assert landing(limit=15) == {"clusters": [1]} and len(calls) == 1      # cached
    assert landing(limit=5) == {"clusters": [2]}                            # other arguments, own entry
    clock[0] += 91
    assert landing(limit=15) == {"clusters": [1]}                           # expired copy served at once
    assert landing(limit=15) == {"clusters": [3]}                           # ...and refreshed behind it


def test_a_failed_refresh_keeps_the_last_good_copy(monkeypatch):
    rc.clear()
    clock = [1000.0]
    monkeypatch.setattr(rc.time, "time", lambda: clock[0])
    monkeypatch.setattr(rc.threading, "Thread", InlineThread)
    state = {"fail": False}

    @rc.cached_response(ttl=90)
    def feed():
        if state["fail"]:
            raise RuntimeError("database timeout")
        return {"clusters": ["good"]}

    assert feed() == {"clusters": ["good"]}
    state["fail"] = True
    clock[0] += 91
    assert feed() == {"clusters": ["good"]}
    assert feed() == {"clusters": ["good"]}


def test_errors_and_not_found_are_never_cached():
    rc.clear()
    calls = []

    @rc.cached_response(ttl=90)
    def story(slug):
        calls.append(slug)
        return {"error": "Cluster not found"}

    story(slug="x"); story(slug="x")
    assert len(calls) == 2


def test_cache_keeps_the_route_signature():
    import inspect

    @rc.cached_response(ttl=90)
    def landing(limit: int = 40):
        return {}
    assert list(inspect.signature(landing).parameters) == ["limit"]
