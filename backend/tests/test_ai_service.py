from __future__ import annotations

import logging

import groq
import httpx
import pytest

from app.core.config import settings
from app.models.schemas import TranscriptSegment
from app.services import ai_service
from app.services.ai_service import (
    AINotConfiguredError,
    AIResponseError,
    AIUpstreamError,
    build_transcript,
    generate_insights,
)
from tests.fakes import GROQ_REQUEST, VALID_INSIGHTS, FakeGroq


def segments(count: int, text: str = "We discussed the roadmap.") -> list[TranscriptSegment]:
    return [
        TranscriptSegment(
            id=f"s{n}",
            meeting_id="m1",
            sequence=n,
            speaker="Speaker 1",
            text=f"{text} ({n})",
            timestamp=n * 7.5,
            confidence=0.9,
        )
        for n in range(1, count + 1)
    ]


async def test_valid_reply_becomes_insights(fake_groq: type[FakeGroq]) -> None:
    fake_groq.reset(VALID_INSIGHTS)
    insights = await generate_insights("m1", "Roadmap", segments(3))

    assert insights.meeting_id == "m1"
    assert insights.summary == VALID_INSIGHTS["summary"]
    assert insights.decisions == VALID_INSIGHTS["decisions"]
    (request,) = fake_groq.requests_made()
    assert request["model"] == settings.groq_model
    assert request["temperature"] == settings.groq_temperature
    assert request["max_tokens"] == settings.groq_max_tokens
    assert request["response_format"] == {"type": "json_object"}
    assert "[00:07] Speaker 1: We discussed the roadmap. (1)" in request["messages"][1]["content"]


def test_default_model_is_a_supported_reasoning_model() -> None:
    # llama-3.3-70b-versatile was shut down for free and developer tiers on 2026-08-16.
    fields = type(settings).model_fields
    assert fields["groq_model"].default == "openai/gpt-oss-120b"
    assert fields["groq_reasoning_effort"].default == "low"


async def test_reasoning_effort_is_sent_when_set(
    fake_groq: type[FakeGroq], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_reasoning_effort", "medium")
    fake_groq.reset(VALID_INSIGHTS)
    await generate_insights("m1", "Roadmap", segments(2))
    (request,) = fake_groq.requests_made()
    assert request["reasoning_effort"] == "medium"


async def test_reasoning_effort_is_omitted_when_blank(
    fake_groq: type[FakeGroq], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Models without reasoning support reject the parameter.
    monkeypatch.setattr(settings, "groq_reasoning_effort", "")
    fake_groq.reset(VALID_INSIGHTS)
    await generate_insights("m1", "Roadmap", segments(2))
    (request,) = fake_groq.requests_made()
    assert "reasoning_effort" not in request


@pytest.mark.parametrize(
    "bad_reply",
    [
        "Sure! Here are your insights: {",
        '{"summary": "Missing the email"}',
        '{"summary": "Objects instead of strings", "follow_up_email": "Hi",'
        ' "action_items": [{"task": "x"}]}',
        groq.BadRequestError(
            "json_validate_failed",
            response=httpx.Response(400, request=GROQ_REQUEST),
            body={"error": {"code": "json_validate_failed", "message": "Failed to generate JSON"}},
        ),
    ],
    ids=["invalid-json", "missing-field", "wrong-type", "groq-json-validation"],
)
async def test_unusable_reply_is_retried_once(
    fake_groq: type[FakeGroq], bad_reply: str | Exception
) -> None:
    fake_groq.reset(bad_reply, VALID_INSIGHTS)
    insights = await generate_insights("m1", "Roadmap", segments(2))

    assert insights.summary == VALID_INSIGHTS["summary"]
    first, retry = fake_groq.requests_made()
    assert retry["messages"][: len(first["messages"])] == first["messages"]
    assert retry["messages"][-1]["content"] == ai_service.CORRECTION_PROMPT


async def test_second_unusable_reply_fails(fake_groq: type[FakeGroq]) -> None:
    fake_groq.reset("not json", "still not json")
    with pytest.raises(AIResponseError):
        await generate_insights("m1", "Roadmap", segments(2))
    assert len(fake_groq.requests_made()) == 2


async def test_provider_errors_are_upstream_errors(fake_groq: type[FakeGroq]) -> None:
    fake_groq.reset(groq.APIConnectionError(request=GROQ_REQUEST))
    with pytest.raises(AIUpstreamError):
        await generate_insights("m1", "Roadmap", segments(2))


async def test_missing_key_is_reported(
    fake_groq: type[FakeGroq], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "")
    with pytest.raises(AINotConfiguredError):
        await generate_insights("m1", "Roadmap", segments(2))
    assert fake_groq.instances == []


async def test_one_client_is_shared_and_closed(fake_groq: type[FakeGroq]) -> None:
    fake_groq.reset(VALID_INSIGHTS, VALID_INSIGHTS)
    await generate_insights("m1", "Roadmap", segments(1))
    await generate_insights("m1", "Roadmap", segments(1))

    (client,) = fake_groq.instances
    assert client.options["api_key"] == "test-groq-key"
    assert client.options["timeout"] == settings.groq_timeout_seconds
    await ai_service.close_client()
    assert client.closed


async def test_long_transcripts_are_shortened_and_logged(
    fake_groq: type[FakeGroq], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(settings, "ai_max_transcript_chars", 2_000)
    fake_groq.reset(VALID_INSIGHTS)
    long_meeting = segments(200)

    with caplog.at_level(logging.WARNING, logger="app.services.ai_service"):
        await generate_insights("m1", "Marathon", long_meeting)

    prompt = fake_groq.requests_made()[0]["messages"][1]["content"]
    transcript = prompt.split("Transcript:\n", 1)[1].rsplit("\n\nAnalyze", 1)[0]
    assert len(transcript) <= 2_000
    assert "(1)" in transcript  # the start of the meeting is kept...
    assert "(200)" in transcript  # ...and so is the end
    assert "transcript lines omitted" in transcript
    assert any("omitted" in record.getMessage() for record in caplog.records)


def test_build_transcript_keeps_short_transcripts_intact() -> None:
    text, omitted = build_transcript(segments(3), 10_000)
    assert omitted == 0
    assert text.count("\n") == 2
    assert text.startswith("[00:07] Speaker 1:")


def test_build_transcript_counts_omitted_lines() -> None:
    lines = segments(100)
    text, omitted = build_transcript(lines, 1_500)
    kept = text.count("Speaker 1:")
    assert kept + omitted == 100
    assert f"[... {omitted} transcript lines omitted" in text
