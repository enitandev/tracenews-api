import app.clusterer as clusterer


class _DB:
    """Records every write; fails a clusters delete for the ids in fail_delete_for."""
    def __init__(self, old_ids, story_rows, fail_delete_for=()):
        self.old_ids, self.story_rows, self.fail = old_ids, story_rows, set(fail_delete_for)
        self.ops = []

    def table(self, name):
        db = self

        class Q:
            def __init__(self):
                self.kind, self.payload, self.filter = "select", None, None

            def select(self, *a, **k):
                return self

            def update(self, payload):
                self.kind, self.payload = "update", payload
                return self

            def delete(self):
                self.kind = "delete"
                return self

            def in_(self, col, ids):
                self.filter = (col, list(ids))
                return self

            def __getattr__(self, _):
                return lambda *a, **k: self

            def execute(self):
                if self.kind == "select":
                    if name == "clusters":
                        return type("R", (), {"data": [{"id": i} for i in db.old_ids]})()
                    ids = set(self.filter[1])
                    return type("R", (), {"data": [r for r in db.story_rows if r["cluster_id"] in ids]})()
                db.ops.append((name, self.kind, self.payload, self.filter))
                if name == "clusters" and self.kind == "delete" and db.fail & set(self.filter[1]):
                    raise RuntimeError("violates foreign key constraint")
                return type("R", (), {"data": []})()
        return Q()


def test_clean_batch_deletes_snapshots_scores_and_clusters(monkeypatch):
    db = _DB(["c1", "c2"], [{"id": "s1", "cluster_id": "c1"}, {"id": "s2", "cluster_id": "c2"}])
    monkeypatch.setattr(clusterer, "supabase", db)
    clusterer.cleanup_old_clusters()
    deletes = [(t, f[1]) for t, kind, _, f in db.ops if kind == "delete"]
    assert ("coverage_snapshots", ["c1", "c2"]) in deletes
    assert ("clusters", ["c1", "c2"]) in deletes
    # no re-attachment when the delete succeeds
    assert not [op for op in db.ops if op[0] == "stories" and op[2] and op[2].get("cluster_id")]


def test_failed_delete_reattaches_the_stories(monkeypatch):
    db = _DB(["c1", "c2"], [{"id": "s1", "cluster_id": "c1"}, {"id": "s2", "cluster_id": "c1"},
                            {"id": "s3", "cluster_id": "c2"}], fail_delete_for=["c1"])
    monkeypatch.setattr(clusterer, "supabase", db)
    clusterer.cleanup_old_clusters()
    restores = {(op[2]["cluster_id"], tuple(op[3][1])) for op in db.ops
                if op[0] == "stories" and op[1] == "update" and op[2].get("cluster_id")}
    assert restores == {("c1", ("s1", "s2")), ("c2", ("s3",))}


def test_one_failed_batch_does_not_stop_the_next(monkeypatch):
    monkeypatch.setattr(clusterer, "CLEANUP_BATCH_SIZE", 1)
    db = _DB(["bad", "good"], [], fail_delete_for=["bad"])
    monkeypatch.setattr(clusterer, "supabase", db)
    clusterer.cleanup_old_clusters()
    assert ("clusters", "delete", None, ("id", ["good"])) in db.ops


def test_total_count_timeout_does_not_crash_clustering(monkeypatch):
    calls = []

    class Q:
        def __getattr__(self, _):
            return lambda *a, **k: self

        def execute(self):
            raise RuntimeError("canceling statement due to statement timeout")

    class DB:
        def table(self, _):
            return Q()

    # A story without an embedding is skipped by the loop, so the run goes
    # straight to the total count.
    monkeypatch.setattr(clusterer, "get_recent_unclustered", lambda *a, **k: [{"id": "s"}])
    monkeypatch.setattr(clusterer, "cleanup_old_clusters", lambda: calls.append("cleanup"))
    monkeypatch.setattr(clusterer, "supabase", DB())
    result = clusterer.run_clustering()
    assert result["total_clusters"] is None and calls == ["cleanup"]
