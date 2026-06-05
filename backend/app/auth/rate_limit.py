"""
Lightweight in-memory rate limiting (per client IP × bucket).

Designed for the current single-instance deployment (the pipeline already relies
on process-wide locks). It is a fixed-window counter: cheap, dependency-free, and
good enough to blunt brute-force logins, signup spam, and résumé-upload / run
abuse for a 10–50 user platform. If we ever scale horizontally, swap the store
for Redis behind the same `RateLimiter` interface.

Usage (FastAPI dependency):
    @router.post("/login", dependencies=[Depends(RateLimiter("login", times=10, seconds=60))])

Disabled entirely when settings.rate_limit_enabled is False (e.g. tests).

NOTE: `RateLimiter` is a factory that returns a plain async function (not a
callable class instance). FastAPI resolves a dependency's annotations via the
callable's `__globals__`; a closure carries this module's globals (where
`Request` is imported), whereas a class-instance does not — using a class here
breaks under `from __future__ import annotations`.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Callable, Dict, List, Tuple

from fastapi import HTTPException, Request, status

from app.config import settings

_lock = threading.Lock()
# bucket -> { key -> [timestamps within window] }
_hits: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))


def _client_key(request: Request) -> str:
    """Best-effort client identity. Honours X-Forwarded-For (Render/Vercel put the
    real client first) and falls back to the socket peer."""
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _check(bucket: str, key: str, times: int, seconds: int) -> Tuple[bool, int]:
    now = time.time()
    cutoff = now - seconds
    with _lock:
        stamps = _hits[bucket][key]
        # Drop expired hits (keeps memory bounded under steady traffic).
        stamps[:] = [t for t in stamps if t > cutoff]
        if len(stamps) >= times:
            retry_after = int(stamps[0] + seconds - now) + 1
            return False, max(retry_after, 1)
        stamps.append(now)
        return True, 0


def reset() -> None:
    """Clear all counters (used by tests)."""
    with _lock:
        _hits.clear()


def RateLimiter(bucket: str, times: int, seconds: int) -> Callable:
    """Build a per-IP fixed-window limiter dependency for one route bucket."""

    async def _dependency(request: Request) -> None:
        if not settings.rate_limit_enabled:
            return
        key = _client_key(request)
        ok, retry_after = _check(bucket, key, times, seconds)
        if not ok:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many requests. Try again in {retry_after}s.",
                headers={"Retry-After": str(retry_after)},
            )

    return _dependency
