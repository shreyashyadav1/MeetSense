"""The application's single rate limiter.

Keys are client IPs. Behind a proxy they are only correct because uvicorn runs
with ``proxy_headers`` and ``FORWARDED_ALLOW_IPS`` (see ``main.py``), which
rewrites the ASGI client address from X-Forwarded-For.
"""

from __future__ import annotations

import logging
import time

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    headers: dict[str, str] = {}
    current = getattr(request.state, "view_rate_limit", None)
    if current is not None:
        try:
            reset_at, _ = limiter.limiter.get_window_stats(current[0], *current[1])
            headers["Retry-After"] = str(max(1, int(reset_at - time.time()) + 1))
        except Exception:  # the header is a courtesy; never fail the response over it
            logger.debug("Could not compute Retry-After", exc_info=True)
    return JSONResponse(
        status_code=429,
        content={"detail": f"Rate limit exceeded: {exc.detail}. Please slow down."},
        headers=headers,
    )
