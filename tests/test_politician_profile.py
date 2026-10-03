import pytest
from fastapi import HTTPException

import app.coverage as coverage
from app.routers import profiles


class _Q:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.r = db, table, {}, (0, 999)

    def select(self, *a, **k):
        return self

    def eq(self, k, v):
        self.filters[k] = v
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self.r = (0, n - 1)
        return self

    def range(self, a, b):
        self.r = (a, b)
        return self

    def execute(self):
        rows = [r for r in self.db[self.table] if all(r.get(k, v) == v for k, v in self.filters.items() if k in r)]
        return type("R", (), {"data": rows[self.r[0]:self.r[1] + 1]})()


def _db(monkeypatch, status="published", articles=()):
    db = {
        "politicians": [{"id": 1, "slug": "p", "active": True, "publication_status": status, "common_name": "P"}],
        "story_entities": [{"story_id": sid, "politician_id": 1, "entity_type": "politician",
                            "stories": {"id": sid, "outlet_id": oid}} for sid, oid in articles],
    }
    monkeypatch.setattr(profiles, "supabase", type("DB", (), {"table": lambda self, t: _Q(db, t)})())
    monkeypatch.setattr(coverage, "get_outlets_cache", lambda: ({
        10: {"government_alignment": "pro_government"}, 11: {"government_alignment": "opposition"},
        12: {"government_alignment": None}}, {}))


@pytest.mark.parametrize("status", ["pending_review", "excluded"])
def test_held_and_private_people_are_404(monkeypatch, status):
    _db(monkeypatch, status=status, articles=[("a", 10)])
    with pytest.raises(HTTPException) as e:
        profiles.get_politician("p")
    assert e.value.status_code == 404
    assert profiles.politician_visibility("p") == {"visible": False}


def test_no_data_is_404(monkeypatch):
    _db(monkeypatch, articles=[])
    with pytest.raises(HTTPException) as e:
        profiles.get_politician("p")
    assert e.value.status_code == 404
    assert profiles.politician_visibility("p") == {"visible": False}


def test_counts_are_articles_by_outlet_tier(monkeypatch):
    _db(monkeypatch, articles=[("a", 10), ("b", 10), ("c", 11), ("d", 12), ("a", 10)])
    res = profiles.get_politician("p")
    assert res["total_articles"] == 4
    assert res["article_counts"] == {"govt_aligned": 2, "mainstream": 0, "watchdog": 1, "untiered": 1}
    assert "tier_distribution" not in res and res["as_of"]
