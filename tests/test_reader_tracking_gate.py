import pytest
from fastapi import HTTPException

from app.routers import reader


class _DB:
    def __init__(self, profile):
        self.profile = profile

    def table(self, name):
        db = self

        class Q:
            def __getattr__(self, _):
                return lambda *a, **k: self

            def execute(self):
                return type("R", (), {"data": [db.profile] if name == "profiles" and db.profile else []})()
        return Q()


@pytest.mark.parametrize("profile,expected", [({"role": "reader", "is_staff": False}, False),
                                              ({"role": None, "is_staff": False}, False),
                                              ({"role": "admin", "is_staff": True}, True)])
def test_tracking_only_for_staff_until_consent_review_closes(monkeypatch, profile, expected):
    monkeypatch.setattr(reader, "CONSENT_REVIEW_CLOSED", False)
    monkeypatch.setattr(reader, "supabase", _DB(profile))
    assert reader.tracking_available("u") is expected


def test_reader_cannot_switch_tracking_on(monkeypatch):
    monkeypatch.setattr(reader, "CONSENT_REVIEW_CLOSED", False)
    monkeypatch.setattr(reader, "supabase", _DB({"role": "reader", "is_staff": False}))
    with pytest.raises(HTTPException) as e:
        reader.submit_consent(reader.ConsentRequest(granted=True), "u")
    assert e.value.status_code == 403
    with pytest.raises(HTTPException) as e:
        reader.track_read(reader.TrackReadRequest(tier="govt", verdict="clear"), "u")
    assert e.value.status_code == 403
