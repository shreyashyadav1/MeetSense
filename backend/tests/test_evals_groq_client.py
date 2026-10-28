from __future__ import annotations

from typing import Any

import groq
import pytest

from app.core.config import settings
from app.models.schemas import TranscriptSegment
from app.services.ai_service import generate_insights
from evals.groq_client import request_insights
from tests.fakes import GROQ_REQUEST, VALID_INSIGHTS, FakeGroq


def request_options(request: dict[str, Any]) -> dict[str, Any]:
    """Everything sent to Groq except the (differently built) messages."""
    return {key: value for key, value in request.items() if key != "messages"}


@pytest.mark.parametrize("effort", ["low", "medium", ""])
async def test_request_options_match_production(
    fake_groq: type[FakeGroq], monkeypatch: pytest.MonkeyPatch, effort: str
) -> None:
    """The eval must call Groq the way generate_insights does, or it measures something else."""
    monkeypatch.setattr(settings, "groq_reasoning_effort", effort)
    segment = TranscriptSegment(
        id="s1",
        meeting_id="m1",
        sequence=1,
        speaker="Alice",
        text="Hello.",
        timestamp=0.0,
        confidence=0.9,
    )

    fake_groq.reset(VALID_INSIGHTS)
    await generate_insights("m1", "Standup", [segment])
    (production_request,) = fake_groq.requests_made()

    FakeGroq.reset(VALID_INSIGHTS)
    client = FakeGroq()
    await request_insights(client, "Standup", "[00:00] Alice: Hello.")
    (eval_request,) = client.requests

    assert request_options(eval_request) == request_options(production_request)
    # A blank effort is omitted entirely: models without reasoning support reject the parameter.
    assert ("reasoning_effort" in eval_request) == bool(effort)


async def test_valid_reply_returns_content_and_token_usage() -> None:
    FakeGroq.reset(VALID_INSIGHTS)
    client = FakeGroq()

    result = await request_insights(client, "Standup", "[00:00] Alice: hi")

    assert result.content is not None
    assert result.content.summary == VALID_INSIGHTS["summary"]
    assert result.prompt_tokens > 0
    assert result.completion_tokens > 0
    assert result.latency_seconds >= 0
    assert result.retried is False
    assert result.error is None


async def test_bad_json_is_retried_once_and_tokens_from_both_calls_are_summed() -> None:
    FakeGroq.reset("not json", VALID_INSIGHTS)
    client = FakeGroq()

    result = await request_insights(client, "Standup", "[00:00] Alice: hi")

    assert result.content is not None
    assert result.retried is True
    first_call, retry_call = client.requests
    first_tokens = sum(len(m["content"]) for m in first_call["messages"]) // 4
    retry_tokens = sum(len(m["content"]) for m in retry_call["messages"]) // 4
    # Both calls' prompt tokens count, not just the last one.
    assert result.prompt_tokens == first_tokens + retry_tokens
    assert result.prompt_tokens > first_tokens


async def test_second_bad_reply_returns_no_content_but_still_reports_usage() -> None:
    FakeGroq.reset("not json", "still not json")
    client = FakeGroq()

    result = await request_insights(client, "Standup", "[00:00] Alice: hi")

    assert result.content is None
    assert result.retried is True
    assert result.error is not None
    assert result.prompt_tokens > 0


async def test_provider_error_is_reported_without_raising() -> None:
    FakeGroq.reset(groq.APIConnectionError(request=GROQ_REQUEST))
    client = FakeGroq()

    result = await request_insights(client, "Standup", "[00:00] Alice: hi")

    assert result.content is None
    assert result.error is not None
    assert result.prompt_tokens == 0


async def test_provider_error_on_retry_is_also_reported_without_raising() -> None:
    # First call returns unparseable JSON (triggers the retry); the retry
    # itself then fails at the provider level.
    FakeGroq.reset("not json", groq.APIConnectionError(request=GROQ_REQUEST))
    client = FakeGroq()

    result = await request_insights(client, "Standup", "[00:00] Alice: hi")

    assert result.content is None
    assert result.retried is True
    assert result.error is not None
    assert result.prompt_tokens > 0  # the first (bad-JSON) call's tokens still count
