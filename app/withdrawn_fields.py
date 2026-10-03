"""
Fields withdrawn from every public API response (counsel, 3 Oct 2026, A7).

The composite TII, its signal scores and the per-outlet S2 are withdrawn
until counsel clears their display; party proximity and the promotional-
alignment flag are claims about named outlets with no evidence file yet.
Dropping them in one place means no endpoint (including /outlets, which
returns every column) can leak them. Staff routes are exempt.
"""
import json

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

WITHDRAWN_FIELDS = frozenset({
    "independence_score", "outlet_independence", "average_independence_score",
    "s1_score", "s2_score", "s3_score", "s4_score", "s5_score", "s6_score", "outlet_s2_score",
    "promotional_alignment_flag", "promotional_alignment_count",
    "party_proximity",
})
STAFF_PREFIXES = ("/admin", "/api/admin")


def strip_withdrawn(obj):
    if isinstance(obj, dict):
        return {k: strip_withdrawn(v) for k, v in obj.items() if k not in WITHDRAWN_FIELDS}
    if isinstance(obj, list):
        return [strip_withdrawn(v) for v in obj]
    return obj


class WithdrawnFieldsMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        if request.url.path.startswith(STAFF_PREFIXES) or "application/json" not in response.headers.get("content-type", ""):
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            payload = strip_withdrawn(json.loads(body))
        except ValueError:
            return Response(body, status_code=response.status_code, headers=dict(response.headers))
        headers = {k: v for k, v in response.headers.items() if k.lower() != "content-length"}
        return Response(json.dumps(payload), status_code=response.status_code, headers=headers, media_type="application/json")
