from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings, settings
from app.models.schemas import Meeting, MeetingInsights
from app.services import github_export
from app.services.smart_meeting_store import smart_meeting_store

EXPORT_KEY = "test-export-key"
REPO = "acme/roadmap"
ACTION_ITEMS = [
    "Alice drafts the release notes",
    "Bob books the venue for the offsite",
    "Carol reviews the onboarding copy",
]


class FakeGitHub:
    """The two GitHub endpoints the exporter uses, backed by a list of issues."""

    def __init__(self) -> None:
        self.issues: list[dict[str, Any]] = []
        self.requests: list[httpx.Request] = []
        self.fail_create_after: int | None = None
        self.list_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        assert request.url.path == f"/repos/{REPO}/issues"
        if request.method == "GET":
            if self.list_status != 200:
                return httpx.Response(self.list_status, json={"message": "Bad credentials"})
            label = request.url.params["labels"]
            page = int(request.url.params["page"])
            per_page = int(request.url.params["per_page"])
            matching = [i for i in self.issues if label in i["labels"]]
            return httpx.Response(200, json=matching[(page - 1) * per_page : page * per_page])
        if self.fail_create_after is not None and len(self.issues) >= self.fail_create_after:
            return httpx.Response(403, json={"message": "Resource not accessible"})
        payload = json.loads(request.content)
        number = len(self.issues) + 1
        issue = {
            "number": number,
            "html_url": f"https://github.com/{REPO}/issues/{number}",
            "title": payload["title"],
            "body": payload["body"],
            "labels": payload["labels"],
        }
        self.issues.append(issue)
        return httpx.Response(201, json=issue)


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeGitHub]:
    fake = FakeGitHub()
    monkeypatch.setattr(github_export, "transport", httpx.MockTransport(fake.handler))
    monkeypatch.setattr(settings, "github_token", "ghp_test")
    monkeypatch.setattr(settings, "github_repository", REPO)
    monkeypatch.setattr(settings, "github_export_key", EXPORT_KEY)
    yield fake


def meeting_with_insights(client: TestClient, items: list[str] = ACTION_ITEMS) -> str:
    meeting_id = client.post("/api/meetings", json={"title": "Planning"}).json()["id"]
    insights = MeetingInsights(
        id="ins-1",
        meeting_id=meeting_id,
        summary="Planned the quarter.",
        action_items=items,
        follow_up_email="Thanks all.",
        generated_at=datetime.now(UTC),
    )
    client.portal.call(smart_meeting_store.save_insights, insights)
    return meeting_id


def export(
    client: TestClient, meeting_id: str, items: list[int], key: str | None = EXPORT_KEY
) -> httpx.Response:
    headers = {"X-Export-Key": key} if key is not None else {}
    return client.post(
        f"/api/meetings/{meeting_id}/action-items/github-issues",
        json={"items": items},
        headers=headers,
    )


# --- Endpoint ----------------------------------------------------------------------


def test_export_files_one_labeled_issue_per_selected_item(
    client: TestClient, github: FakeGitHub
) -> None:
    meeting_id = meeting_with_insights(client)

    response = export(client, meeting_id, [2, 0])

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["repository"] == REPO
    assert [i["action_item"] for i in body["issues"]] == [ACTION_ITEMS[2], ACTION_ITEMS[0]]
    assert [i["created"] for i in body["issues"]] == [True, True]
    assert body["issues"][0]["url"] == f"https://github.com/{REPO}/issues/1"
    first = github.issues[0]
    assert first["title"] == ACTION_ITEMS[2]
    assert first["labels"] == ["meetsense"]
    assert "**Planning**" in first["body"]
    assert github_export.marker(meeting_id, ACTION_ITEMS[2]) in first["body"]
    auth = github.requests[0].headers["Authorization"]
    assert auth == "Bearer ghp_test"


def test_repeating_an_export_reuses_the_existing_issues(
    client: TestClient, github: FakeGitHub
) -> None:
    meeting_id = meeting_with_insights(client)
    assert export(client, meeting_id, [0, 1]).status_code == 200

    response = export(client, meeting_id, [1, 2, 0])

    assert response.status_code == 200
    issues = response.json()["issues"]
    assert [(i["number"], i["created"]) for i in issues] == [(2, False), (3, True), (1, False)]
    assert len(github.issues) == 3


def test_issues_from_another_meeting_are_not_reused(client: TestClient, github: FakeGitHub) -> None:
    first = meeting_with_insights(client)
    second = meeting_with_insights(client)
    export(client, first, [0])

    issues = export(client, second, [0]).json()["issues"]

    assert issues[0]["created"] is True
    assert len(github.issues) == 2


def test_a_failed_export_can_be_retried_without_duplicates(
    client: TestClient, github: FakeGitHub
) -> None:
    meeting_id = meeting_with_insights(client)
    github.fail_create_after = 1

    response = export(client, meeting_id, [0, 1, 2])

    assert response.status_code == 502
    assert "will not create duplicates" in response.json()["detail"]
    assert len(github.issues) == 1

    github.fail_create_after = None
    issues = export(client, meeting_id, [0, 1, 2]).json()["issues"]
    assert [i["created"] for i in issues] == [False, True, True]
    assert len(github.issues) == 3


def test_github_errors_are_reported_without_echoing_details(
    client: TestClient, github: FakeGitHub, caplog: pytest.LogCaptureFixture
) -> None:
    meeting_id = meeting_with_insights(client)
    github.list_status = 401

    response = export(client, meeting_id, [0])

    assert response.status_code == 502
    assert "Bad credentials" not in response.text
    assert "ghp_test" not in caplog.text


def test_repeated_indexes_are_exported_once(client: TestClient, github: FakeGitHub) -> None:
    meeting_id = meeting_with_insights(client)

    issues = export(client, meeting_id, [1, 1, 0, 1]).json()["issues"]

    assert [i["action_item"] for i in issues] == [ACTION_ITEMS[1], ACTION_ITEMS[0]]
    assert len(github.issues) == 2


@pytest.mark.parametrize("key", [None, "", "wrong-key"])
def test_a_missing_or_wrong_export_key_is_rejected(
    client: TestClient, github: FakeGitHub, key: str | None
) -> None:
    meeting_id = meeting_with_insights(client)

    response = export(client, meeting_id, [0], key=key)

    assert response.status_code == 401
    assert github.requests == []


def test_export_is_unavailable_until_configured(client: TestClient) -> None:
    meeting_id = meeting_with_insights(client)

    response = export(client, meeting_id, [0])

    assert response.status_code == 503
    assert response.json()["detail"] == "GitHub export is not configured on this server."


def test_out_of_range_indexes_are_rejected(client: TestClient, github: FakeGitHub) -> None:
    meeting_id = meeting_with_insights(client)

    response = export(client, meeting_id, [0, 3, 7])

    assert response.status_code == 422
    assert "[3, 7]" in response.json()["detail"]
    assert github.requests == []


@pytest.mark.parametrize("items", [[], [-1], list(range(21))])
def test_invalid_selections_fail_validation(
    client: TestClient, github: FakeGitHub, items: list[int]
) -> None:
    meeting_id = meeting_with_insights(client)

    assert export(client, meeting_id, items).status_code == 422


def test_export_needs_a_known_meeting_with_insights(client: TestClient, github: FakeGitHub) -> None:
    assert export(client, "missing", [0]).status_code == 404

    meeting_id = client.post("/api/meetings", json={"title": "No insights"}).json()["id"]
    response = export(client, meeting_id, [0])
    assert response.status_code == 404
    assert "summarize" in response.json()["detail"]


# --- Helpers and settings ------------------------------------------------------------


def test_item_keys_ignore_case_and_spacing() -> None:
    assert github_export.item_key("Alice  drafts the\nnotes") == github_export.item_key(
        "alice drafts the notes"
    )
    assert github_export.item_key("Alice drafts") != github_export.item_key("Bob drafts")


def test_long_titles_are_cut_to_githubs_limit() -> None:
    title = github_export.issue_title("word " * 100)
    assert len(title) <= github_export.TITLE_MAX_LENGTH
    assert title.endswith("…")


def test_issue_body_dates_are_in_utc() -> None:
    meeting = Meeting(
        id="m-1",
        title="Sync",
        status="ended",
        started_at=datetime.fromisoformat("2026-10-19T09:30:00-04:00"),
    )
    assert "(2026-10-19 13:30 UTC)" in github_export.issue_body(meeting, "Ship it")


@pytest.mark.parametrize("value", ["acme", "acme/", "/repo", "a b/c", "acme/repo/extra"])
def test_malformed_repositories_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="owner/name"):
        Settings(github_repository=value)


def test_export_needs_token_repository_and_key() -> None:
    assert not Settings.model_construct(
        github_token="t", github_repository=REPO
    ).github_export_configured
    assert Settings.model_construct(
        github_token="t", github_repository=REPO, github_export_key="k"
    ).github_export_configured
