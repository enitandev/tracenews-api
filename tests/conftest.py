import pytest


@pytest.fixture(autouse=True)
def _fresh_response_cache():
    """Each test sees the endpoints uncached (app/response_cache.py)."""
    from app import admin_auth, response_cache
    response_cache.clear()
    admin_auth._identities.clear()
    yield
    response_cache.clear()
    admin_auth._identities.clear()
