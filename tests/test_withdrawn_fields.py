from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.withdrawn_fields import WithdrawnFieldsMiddleware

app = FastAPI()
app.add_middleware(WithdrawnFieldsMiddleware)
SAMPLE = {"outlet": {"name": "X", "independence_score": 42, "party_proximity": "APC", "tier": "mainstream"},
          "stories": [{"outlet_s2_score": 20, "outlet_republishes": True, "coverage_stats": {"average_independence_score": 50, "total_coverage": 6}}]}


@app.get("/outlets/x")
def public():
    return SAMPLE


@app.get("/api/admin/thing")
def staff():
    return SAMPLE


def test_public_responses_drop_withdrawn_fields():
    body = TestClient(app).get("/outlets/x").json()
    assert body == {"outlet": {"name": "X", "tier": "mainstream"},
                    "stories": [{"outlet_republishes": True, "coverage_stats": {"total_coverage": 6}}]}


def test_staff_routes_keep_them():
    assert TestClient(app).get("/api/admin/thing").json() == SAMPLE
