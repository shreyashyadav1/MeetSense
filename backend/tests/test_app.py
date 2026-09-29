"""Application-level behavior: health reporting and CORS."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import create_app
from app.services.smart_meeting_store import smart_meeting_store


def test_health_in_demo_mode(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "degraded",
        "database": "memory",
        "redis": "unavailable",
        "transcription": "mock",
        "ai": "not_configured",
    }


def test_health_reports_configured_services_without_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "deepgram_api_key", "dg-secret-key")
    monkeypatch.setattr(settings, "groq_api_key", "gsk-secret-key")
    with TestClient(create_app()) as client:
        response = client.get("/health")
    body = response.json()
    assert body["transcription"] == "deepgram"
    assert body["ai"] == "configured"
    assert "secret" not in response.text


def test_health_is_503_when_the_database_is_down_without_fallback(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable() -> str:
        return "unavailable"

    monkeypatch.setattr(smart_meeting_store, "health", unavailable)
    response = client.get("/health")
    assert response.status_code == 503
    assert response.json()["database"] == "unavailable"
    assert response.json()["status"] == "degraded"


@pytest.mark.postgres
@pytest.mark.redis
def test_health_ok_with_postgres_and_redis(postgres: str, redis_enabled: str) -> None:
    with TestClient(create_app()) as client:
        body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["database"] == "postgres"
    assert body["redis"] == "connected"


def _preflight(client: TestClient, origin: str) -> httpx.Response:
    return client.options(
        "/api/meetings",
        headers={"Origin": origin, "Access-Control-Request-Method": "POST"},
    )


def test_cors_allows_configured_origins_without_credentials(client: TestClient) -> None:
    response = _preflight(client, "https://meet-sense.vercel.app")
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "https://meet-sense.vercel.app"
    assert "access-control-allow-credentials" not in response.headers

    denied = _preflight(client, "https://evil.example")
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_cors_origins_come_from_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "allowed_origins", ["https://staging.example"])
    with TestClient(create_app()) as client:
        assert _preflight(client, "https://staging.example").status_code == 200
        assert _preflight(client, "https://meet-sense.vercel.app").status_code == 400
