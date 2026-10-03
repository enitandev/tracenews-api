import pytest
from fastapi import HTTPException

from app.routers import briefing


@pytest.mark.parametrize("call", [lambda: briefing.get_daily_briefing(), lambda: briefing.get_daily_briefing_story("any")])
def test_briefing_endpoints_return_410(call):
    with pytest.raises(HTTPException) as e:
        call()
    assert e.value.status_code == 410
