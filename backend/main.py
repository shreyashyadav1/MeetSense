"""Entry point: ``python main.py`` (used by Railway, the Procfile and Docker)."""

import logging

import uvicorn

from app.core.config import settings
from app.main import app

__all__ = ["app"]  # keeps `uvicorn main:app` working


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    uvicorn.run(
        app,
        host="0.0.0.0",  # all interfaces: the process runs in a container
        port=settings.port,
        # Take the client IP from X-Forwarded-For when the peer is a trusted
        # proxy, so rate limits and socket caps apply per visitor.
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
        timeout_graceful_shutdown=10,
        log_level="info",
    )


if __name__ == "__main__":
    main()
