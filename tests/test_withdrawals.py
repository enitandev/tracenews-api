import pytest
from fastapi import HTTPException

from app.routers import briefing


@pytest.mark.parametrize("call", [lambda: briefing.get_daily_briefing(), lambda: briefing.get_daily_briefing_story("any")])
def test_briefing_endpoints_return_404_while_off(call, monkeypatch):
    monkeypatch.setattr(briefing, "BRIEFING_PUBLIC", False)
    with pytest.raises(HTTPException) as e:
        call()
    assert e.value.status_code == 404
