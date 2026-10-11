from __future__ import annotations

from typing import Any

import groq
import pytest
from fastapi.testclient import TestClient

from app.models.schemas import TranscriptSegment
from app.services.smart_meeting_store import DatabaseUnavailableError, smart_meeting_store
from tests.fakes import GROQ_REQUEST, VALID_INSIGHTS, FakeGroq


def create_meeting(client: TestClient, title: str = "Weekly sync") -> dict[str, Any]:
    response = client.post("/api/meetings", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()


def seed_transcript(client: TestClient, meeting_id: str, count: int = 3) -> None:
    for sequence in range(1, count + 1):
        segment = TranscriptSegment(
            id=f"seg-{sequence}",
            meeting_id=meeting_id,
            sequence=sequence,
            speaker="Speaker 1",
            text=f"Point number {sequence}.",
            timestamp=float(sequence),
            confidence=0.9,
        )
        client.portal.call(smart_meeting_store.add_segment, segment)


# --- Meetings --------------------------------------------------------------------


def test_create_meeting_trims_the_title(client: TestClient) -> None:
    meeting = create_meeting(client, "  Design review  ")
    assert meeting["title"] == "Design review"
    assert meeting["status"] == "active"
    assert meeting["ended_at"] is None
    assert set(meeting) == {"id", "title", "status", "started_at", "ended_at"}


@pytest.mark.parametrize("title", ["", "   ", "x" * 121, "x" * 256])
def test_invalid_titles_are_rejected(client: TestClient, title: str) -> None:
    response = client.post("/api/meetings", json={"title": title})
    assert response.status_code == 422
    body = response.json()
    assert isinstance(body["detail"], str)
    assert body["detail"].startswith("title:")
    assert body["errors"][0]["loc"] == ["body", "title"]


def test_a_120_character_title_is_accepted(client: TestClient) -> None:
    assert create_meeting(client, "x" * 120)["title"] == "x" * 120


def test_list_meetings_is_newest_first_and_paginated(client: TestClient) -> None:
    ids = [create_meeting(client, f"Meeting {n}")["id"] for n in range(5)]
    newest_first = list(reversed(ids))

    assert [m["id"] for m in client.get("/api/meetings").json()] == newest_first
    page = client.get("/api/meetings", params={"limit": 2, "offset": 1}).json()
    assert [m["id"] for m in page] == newest_first[1:3]
    assert client.get("/api/meetings", params={"offset": 10}).json() == []


@pytest.mark.parametrize("params", [{"limit": 0}, {"limit": 101}, {"offset": -1}])
def test_list_meetings_rejects_bad_pagination(client: TestClient, params: dict[str, int]) -> None:
    assert client.get("/api/meetings", params=params).status_code == 422


def test_get_meeting(client: TestClient) -> None:
    meeting = create_meeting(client)
    assert client.get(f"/api/meetings/{meeting['id']}").json() == meeting
    missing = client.get("/api/meetings/nope")
    assert missing.status_code == 404
    assert missing.json() == {"detail": "Meeting 'nope' not found."}


def test_end_meeting(client: TestClient) -> None:
    meeting = create_meeting(client)
    ended = client.post(f"/api/meetings/{meeting['id']}/end")
    assert ended.status_code == 200
    assert ended.json()["status"] == "ended"
    assert ended.json()["ended_at"] is not None

    assert client.post(f"/api/meetings/{meeting['id']}/end").status_code == 409
    assert client.post("/api/meetings/nope/end").status_code == 404


def test_transcript(client: TestClient) -> None:
    meeting = create_meeting(client)
    assert client.get(f"/api/meetings/{meeting['id']}/transcript").json() == []
    seed_transcript(client, meeting["id"], count=2)
    transcript = client.get(f"/api/meetings/{meeting['id']}/transcript").json()
    assert [s["sequence"] for s in transcript] == [1, 2]
    assert client.get("/api/meetings/nope/transcript").status_code == 404


# --- Insights --------------------------------------------------------------------


def test_summarize_unknown_meeting(client: TestClient) -> None:
    assert client.post("/api/meetings/nope/summarize").status_code == 404


def test_summarize_without_a_transcript_is_a_client_error(
    client: TestClient, fake_groq: type[FakeGroq]
) -> None:
    meeting = create_meeting(client)
    response = client.post(f"/api/meetings/{meeting['id']}/summarize")
    assert response.status_code == 400
    assert response.json() == {"detail": "No transcript available to summarize."}
    assert fake_groq.requests_made() == []


def test_summarize_without_groq_key_is_unavailable(client: TestClient) -> None:
    meeting = create_meeting(client)
    seed_transcript(client, meeting["id"])
    response = client.post(f"/api/meetings/{meeting['id']}/summarize")
    assert response.status_code == 503
    assert response.json() == {"detail": "AI insights are not configured on this server."}


def test_summarize_caches_and_force_regenerates(
    client: TestClient, fake_groq: type[FakeGroq]
) -> None:
    meeting = create_meeting(client)
    seed_transcript(client, meeting["id"])
    fake_groq.reset(VALID_INSIGHTS, {**VALID_INSIGHTS, "summary": "Regenerated summary."})
    url = f"/api/meetings/{meeting['id']}/summarize"

    first = client.post(url)
    assert first.status_code == 200
    assert first.json()["summary"] == VALID_INSIGHTS["summary"]
    assert first.json()["action_items"] == VALID_INSIGHTS["action_items"]

    cached = client.post(url)
    assert cached.json() == first.json()
    assert len(fake_groq.requests_made()) == 1

    forced = client.post(url, params={"force": "true"})
    assert forced.status_code == 200
    assert forced.json()["summary"] == "Regenerated summary."
    assert len(fake_groq.requests_made()) == 2
    assert client.get(f"/api/meetings/{meeting['id']}/insights").json() == forced.json()


def test_get_insights_before_summarize_is_404(client: TestClient) -> None:
    meeting = create_meeting(client)
    assert client.get(f"/api/meetings/{meeting['id']}/insights").status_code == 404


@pytest.mark.parametrize(
    "replies",
    [
        [groq.APIConnectionError(message="secret upstream detail", request=GROQ_REQUEST)],
        ["not json at all", '{"summary": "secret upstream detail"}'],
    ],
    ids=["provider-error", "invalid-output-twice"],
)
def test_summarize_upstream_failures_are_bad_gateway(
    client: TestClient, fake_groq: type[FakeGroq], replies: list[Any]
) -> None:
    meeting = create_meeting(client)
    seed_transcript(client, meeting["id"])
    fake_groq.reset(*replies)
    response = client.post(f"/api/meetings/{meeting['id']}/summarize")
    assert response.status_code == 502
    assert response.json() == {
        "detail": "The AI service could not generate insights. Please try again."
    }
    assert "secret" not in response.text


# --- Cross-cutting ---------------------------------------------------------------


def test_rate_limit_answers_with_detail_and_retry_after(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.rate_limit import limiter

    monkeypatch.setattr(limiter, "enabled", True)
    for _ in range(20):
        create_meeting(client)
    limited = client.post("/api/meetings", json={"title": "One too many"})
    assert limited.status_code == 429
    assert limited.json()["detail"].startswith("Rate limit exceeded: 20 per 1 minute")
    assert int(limited.headers["Retry-After"]) >= 1


def test_the_app_and_routers_share_one_limiter() -> None:
    from app.api import meetings
    from app.main import app

    assert app.state.limiter is meetings.limiter


def test_unhandled_errors_return_json_without_details(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.main import app

    async def broken(meeting_id: str) -> None:
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(smart_meeting_store, "get_meeting", broken)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/meetings/anything")
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal server error."}


def test_database_outage_without_fallback_is_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unavailable(meeting_id: str) -> None:
        raise DatabaseUnavailableError("PostgreSQL is unavailable")

    monkeypatch.setattr(smart_meeting_store, "get_meeting", unavailable)
    response = client.get("/api/meetings/anything")
    assert response.status_code == 503
    assert response.json() == {"detail": "The database is unavailable. Please try again."}
