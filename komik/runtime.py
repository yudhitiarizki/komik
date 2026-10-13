"""Shared source instances with one lock per site, so the API, the in-app
scheduler and manual checks never hit the same site in parallel and the
per-site rate limit is respected across them."""
import threading
from contextlib import contextmanager

from .sources import SOURCES

_guard = threading.Lock()
_sources: dict = {}
_locks: dict = {}
DELAY = 1.0


@contextmanager
def using(name):
    if name not in SOURCES:
        raise KeyError(name)
    with _guard:
        lock = _locks.setdefault(name, threading.Lock())
        if name not in _sources:
            _sources[name] = SOURCES[name](delay=DELAY)
    with lock:
        yield _sources[name]
