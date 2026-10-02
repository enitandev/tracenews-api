import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import app.main as main
    monkeypatch.setattr(main, "start_scheduler", lambda: None)
    monkeypatch.setattr(main, "stop_scheduler", lambda: None)

    @main.app.get("/__boom")
    def boom():
        raise RuntimeError("secret internal detail")

    yield TestClient(main.app, raise_server_exceptions=False)
    main.app.router.routes = [r for r in main.app.router.routes if getattr(r, "path", "") != "/__boom"]


def test_unhandled_error_returns_no_traceback(client):
    r = client.get("/__boom", headers={"Origin": "https://tracenews.ng"})
    assert r.status_code == 500
    assert r.json() == {"detail": "Internal Server Error"}
    assert "secret internal detail" not in r.text and "Traceback" not in r.text


def test_error_cors_only_for_allowed_origins(client):
    ok = client.get("/__boom", headers={"Origin": "https://tracenews.ng"})
    assert ok.headers.get("access-control-allow-origin") == "https://tracenews.ng"
    evil = client.get("/__boom", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in evil.headers
    assert "access-control-allow-credentials" not in evil.headers


@pytest.mark.parametrize("path", ["/admin/fetch", "/admin/cluster", "/admin/run", "/admin/recluster-all"])
def test_pipeline_triggers_reject_anonymous_callers(client, monkeypatch, path):
    import app.routers.system as system
    ran = []
    monkeypatch.setattr(system, "run_fetch", lambda: ran.append("fetch") or {})
    monkeypatch.setattr(system, "run_clustering", lambda: ran.append("cluster") or {})
    monkeypatch.setattr(system, "run_full_recluster", lambda: ran.append("recluster"))
    r = client.post(path)
    assert r.status_code in (401, 403, 422)
    assert ran == []
