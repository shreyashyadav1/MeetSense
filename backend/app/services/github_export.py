"""Export a meeting's action items as GitHub issues.

Each issue body carries a hidden marker naming the meeting and a hash of the
action item. Before creating anything, the exporter lists the repository's
issues with the export label (open and closed) and reuses any issue whose
marker matches, so a retried or repeated export never files duplicates.
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC

import httpx

from app.core.config import settings
from app.models.schemas import Meeting

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 256  # GitHub's limit for issue titles
MAX_LISTED_PAGES = 10  # 1,000 labeled issues; older exports beyond that are not checked
_MARKER = re.compile(r"<!-- meetsense-export meeting=(\S+) item=([0-9a-f]{16}) -->")

# Tests swap in an httpx.MockTransport.
transport: httpx.AsyncBaseTransport | None = None


class GitHubExportError(Exception):
    """GitHub could not be reached or refused a request. Messages are for logs."""


@dataclass(frozen=True)
class ExportedIssue:
    action_item: str
    number: int
    url: str
    created: bool


def item_key(action_item: str) -> str:
    """A stable id for an action item: case- and whitespace-insensitive."""
    normalized = " ".join(action_item.split()).casefold()
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]


def marker(meeting_id: str, action_item: str) -> str:
    return f"<!-- meetsense-export meeting={meeting_id} item={item_key(action_item)} -->"


def issue_title(action_item: str) -> str:
    title = " ".join(action_item.split())
    if len(title) > TITLE_MAX_LENGTH:
        title = title[: TITLE_MAX_LENGTH - 1].rstrip() + "…"
    return title


def issue_body(meeting: Meeting, action_item: str) -> str:
    return (
        f"{action_item.strip()}\n\n"
        f"Action item from the meeting **{meeting.title}** "
        f"({meeting.started_at.astimezone(UTC):%Y-%m-%d %H:%M} UTC), exported from MeetSense.\n\n"
        f"{marker(meeting.id, action_item)}\n"
    )


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=settings.github_api_url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.github_token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "meetsense-backend",
        },
        timeout=settings.github_timeout_seconds,
        transport=transport,
    )


async def _request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    *,
    params: dict[str, str | int] | None = None,
    json: dict[str, object] | None = None,
) -> object:
    try:
        response = await client.request(method, path, params=params, json=json)
    except httpx.HTTPError as error:
        raise GitHubExportError(f"{method} {path} failed: {type(error).__name__}") from None
    if response.status_code >= 400:
        # The body can echo request details; log only the status and GitHub's message.
        try:
            message = response.json().get("message", "")
        except ValueError:
            message = ""
        raise GitHubExportError(f"{method} {path} returned {response.status_code}: {message}")
    try:
        return response.json()
    except ValueError:
        raise GitHubExportError(f"{method} {path} returned a non-JSON body") from None


async def _existing_exports(client: httpx.AsyncClient, meeting_id: str) -> dict[str, dict]:
    """Issues already exported for this meeting, keyed by action-item hash."""
    repo = settings.github_repository
    found: dict[str, dict] = {}
    for page in range(1, MAX_LISTED_PAGES + 1):
        issues = await _request(
            client,
            "GET",
            f"/repos/{repo}/issues",
            params={
                "labels": settings.github_issue_label,
                "state": "all",
                "per_page": 100,
                "page": page,
            },
        )
        if not isinstance(issues, list):
            raise GitHubExportError("issue list was not a JSON array")
        for issue in issues:
            if not isinstance(issue, dict) or "pull_request" in issue:
                continue
            for match in _MARKER.finditer(issue.get("body") or ""):
                if match.group(1) == meeting_id:
                    found.setdefault(match.group(2), issue)
        if len(issues) < 100:
            break
    return found


async def export_action_items(meeting: Meeting, action_items: Sequence[str]) -> list[ExportedIssue]:
    """Create one issue per action item, reusing issues from earlier exports.

    Items are handled in order. If GitHub fails partway, the issues created so
    far stay, and calling again picks up where this call stopped.
    """
    repo = settings.github_repository
    results: list[ExportedIssue] = []
    async with _client() as client:
        existing = await _existing_exports(client, meeting.id)
        for action_item in action_items:
            key = item_key(action_item)
            issue = existing.get(key)
            created = issue is None
            if issue is None:
                issue = await _request(
                    client,
                    "POST",
                    f"/repos/{repo}/issues",
                    json={
                        "title": issue_title(action_item),
                        "body": issue_body(meeting, action_item),
                        "labels": [settings.github_issue_label],
                    },
                )
                if not isinstance(issue, dict):
                    raise GitHubExportError("created issue was not a JSON object")
                existing[key] = issue
            try:
                results.append(
                    ExportedIssue(
                        action_item=action_item,
                        number=int(issue["number"]),
                        url=str(issue["html_url"]),
                        created=created,
                    )
                )
            except (KeyError, TypeError, ValueError):
                raise GitHubExportError("issue is missing its number or URL") from None
    logger.info(
        "Exported %d action items of meeting %s to %s (%d new)",
        len(results),
        meeting.id,
        repo,
        sum(r.created for r in results),
    )
    return results
