import os
import httpx
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

url: str = os.environ["SUPABASE_URL"]
key: str = os.environ["SUPABASE_SERVICE_KEY"]

# Patch httpx.Client to universally enforce keepalive limits and retry on RemoteProtocolError.
# This prevents stale HTTP/2 connections from causing 500s when Supabase drops idle connections.
# The idle connection issue surfaced after the worker was split, causing the API to idle 
# between legitimate requests rather than having connections kept warm by the in-process scheduler.

original_init = httpx.Client.__init__

def custom_init(self, *args, **kwargs):
    limits = kwargs.get("limits")
    if limits is None:
        # A low keepalive expiry (10s) ensures httpx actively discards idle connections
        # BEFORE Supabase's edge terminates them.
        kwargs["limits"] = httpx.Limits(keepalive_expiry=10.0)
    else:
        kwargs["limits"] = httpx.Limits(
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=10.0
        )
    original_init(self, *args, **kwargs)

httpx.Client.__init__ = custom_init

original_request = httpx.Client.request

def retrying_request(self, *args, **kwargs):
    try:
        return original_request(self, *args, **kwargs)
    except httpx.RemoteProtocolError:
        # The pool may hold MULTIPLE stale connections. If we just retry, we might 
        # pull the next stale one and fail again. We close the transport to purge 
        # the entire pool, guaranteeing a fresh connection.
        if hasattr(self, "_transport"):
            self._transport.close()
        return original_request(self, *args, **kwargs)

httpx.Client.request = retrying_request

def get_client() -> Client:
    return create_client(url, key)

supabase: Client = get_client()