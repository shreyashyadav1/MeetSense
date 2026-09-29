from __future__ import annotations

import groq

from evals.groq_client import request_insights
from tests.fakes import GROQ_REQUEST, VALID_INSIGHTS, FakeGroq


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
