import app.coverage as coverage
from app.routers.feeds import passes_homepage_floor, HOMEPAGE_MIN_SCORED_OUTLETS


def stats(g, m, w):
    return {"coverage_stats": {"coverage_tier_distribution": {"govt_aligned": g, "mainstream": m, "watchdog": w}}}


def test_floor_is_three_distinct_scored_outlets():
    assert HOMEPAGE_MIN_SCORED_OUTLETS == 3
    assert passes_homepage_floor(stats(1, 1, 1))
    assert not passes_homepage_floor(stats(0, 2, 0))


def test_unknown_counts_never_pass():
    assert not passes_homepage_floor({"coverage_stats": None})
    assert not passes_homepage_floor({"coverage_stats": {"coverage_tier_distribution": {"Institutional": 9}}})


class _PagedDB:
    """Serves `total` story rows for each requested cluster, honouring range()."""
    def __init__(self, per_cluster):
        self.per_cluster = per_cluster
        self.calls = []

    def table(self, _):
        db = self

        class Q:
            def __init__(self):
                self.ids, self.lo, self.hi = [], 0, None

            def select(self, *a, **k):
                return self

            def in_(self, col, ids):
                self.ids = ids
                return self

            def order(self, *a, **k):
                return self

            def range(self, lo, hi):
                self.lo, self.hi = lo, hi
                return self

            def execute(self):
                rows = [{"id": f"{cid}-{n}", "cluster_id": cid, "outlet_id": f"o{n}"}
                        for cid in self.ids for n in range(db.per_cluster)]
                db.calls.append((len(self.ids), self.lo, self.hi))
                return type("R", (), {"data": rows[self.lo:self.hi + 1]})()
        return Q()


def test_story_fetch_pages_past_the_row_cap(monkeypatch):
    db = _PagedDB(per_cluster=30)   # 50 clusters x 30 = 1500 rows per batch > 1000 cap
    monkeypatch.setattr(coverage, "supabase", db)
    ids = [f"c{i}" for i in range(120)]
    rows = coverage.fetch_cluster_story_outlets(ids)
    assert len(rows) == 120 * 30
    assert {r["cluster_id"] for r in rows} == set(ids)
    assert max(n for n, _, _ in db.calls) <= coverage.CLUSTER_ID_BATCH
