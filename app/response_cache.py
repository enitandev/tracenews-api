"""
Cache for public read endpoints whose data only changes when the worker runs
(every 20 minutes): homepage lists, category sections, story pages.

Each response is kept for `ttl` seconds per set of arguments. After that the
cached copy is still served at once and a fresh one is built in the
background, so a reader never waits for a rebuild; only the first request for
a given set of arguments builds in line. If a rebuild fails, the error is
logged and the last good copy keeps being served. Exceptions (e.g. a 404)
and {"error": ...} replies are never cached.
"""
import functools
import logging
import threading
import time

logger = logging.getLogger(__name__)

MAX_ENTRIES = 500
_entries = {}            # key -> {"at": float, "value": object}
_locks = {}              # key -> threading.Lock (one rebuild at a time per key)
_guard = threading.Lock()


def _lock_for(key):
    with _guard:
        return _locks.setdefault(key, threading.Lock())


def _cacheable(value):
    return not (isinstance(value, dict) and "error" in value)


def _store(key, value):
    if not _cacheable(value):
        return
    with _guard:
        if len(_entries) >= MAX_ENTRIES and key not in _entries:
            oldest = min(_entries, key=lambda k: _entries[k]["at"])
            _entries.pop(oldest, None)
            _locks.pop(oldest, None)
        _entries[key] = {"at": time.time(), "value": value}


def clear():
    with _guard:
        _entries.clear()


def _refresh(key, fn, args, kwargs):
    lock = _lock_for(key)
    if not lock.acquire(blocking=False):
        return
    try:
        _store(key, fn(*args, **kwargs))
    except Exception:
        logger.exception(f"[cache] background refresh failed for {key[0]}; serving the last good copy")
    finally:
        lock.release()


def cached_response(ttl=90):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            key = (fn.__name__, args, tuple(sorted(kwargs.items())))
            entry = _entries.get(key)
            if entry is None:
                with _lock_for(key):
                    entry = _entries.get(key)
                    if entry is None:
                        value = fn(*args, **kwargs)
                        _store(key, value)
                        return value
            if time.time() - entry["at"] >= ttl:
                threading.Thread(target=_refresh, args=(key, fn, args, kwargs), daemon=True).start()
            return entry["value"]
        return wrapper
    return decorate
