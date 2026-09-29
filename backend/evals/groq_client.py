"""A direct Groq call for the eval harness, with token usage attached.

``app.services.ai_service.generate_insights`` is the production path, but it
returns ``MeetingInsights`` - the schema stored in Postgres and served over
the API - which has no room for token usage or per-call latency. Rather than
grow that schema for an offline tool, this mirrors production's prompt and
one-retry-on-bad-JSON policy (reusing its constants directly, so the two
can't drift silently) closely enough to evaluate what a user would actually
see, while returning the numbers the harness needs.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import groq
from groq.types.chat import ChatCompletionMessageParam
from pydantic import ValidationError

from app.core.config import settings
from app.services.ai_service import CORRECTION_PROMPT, SYSTEM_PROMPT, _InsightsContent


@dataclass(frozen=True, slots=True)
class GroqCallResult:
    content: _InsightsContent | None
    prompt_tokens: int
    completion_tokens: int
    latency_seconds: float
    retried: bool
    error: str | None = None


async def request_insights(
    client: groq.AsyncGroq, meeting_title: str, transcript: str
) -> GroqCallResult:
    messages: list[ChatCompletionMessageParam] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Meeting Title: {meeting_title}\n\nTranscript:\n{transcript}\n\n"
                "Analyze this meeting and return the JSON insights."
            ),
        },
    ]
    started = time.perf_counter()
    try:
        reply, (prompt_tokens, completion_tokens) = await _complete(client, messages)
    except groq.APIError as error:
        return GroqCallResult(None, 0, 0, time.perf_counter() - started, False, str(error))

    content, error = _parse(reply)
    retried = False
    if content is None:
        retried = True
        messages = [
            *messages,
            {"role": "assistant", "content": reply or ""},
            {"role": "user", "content": CORRECTION_PROMPT},
        ]
        try:
            reply, (more_prompt, more_completion) = await _complete(client, messages)
        except groq.APIError as api_error:
            elapsed = time.perf_counter() - started
            return GroqCallResult(
                None, prompt_tokens, completion_tokens, elapsed, True, str(api_error)
            )
        prompt_tokens += more_prompt
        completion_tokens += more_completion
        content, error = _parse(reply)

    return GroqCallResult(
        content, prompt_tokens, completion_tokens, time.perf_counter() - started, retried, error
    )


async def _complete(
    client: groq.AsyncGroq, messages: list[ChatCompletionMessageParam]
) -> tuple[str | None, tuple[int, int]]:
    response = await client.chat.completions.create(
        model=settings.groq_model,
        messages=messages,
        temperature=settings.groq_temperature,
        max_tokens=settings.groq_max_tokens,
        response_format={"type": "json_object"},
    )
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
    completion_tokens = getattr(usage, "completion_tokens", 0) or 0
    text = response.choices[0].message.content if response.choices else None
    return text, (prompt_tokens, completion_tokens)


def _parse(reply: str | None) -> tuple[_InsightsContent | None, str | None]:
    if not reply:
        return None, "empty reply"
    try:
        return _InsightsContent.model_validate_json(reply), None
    except ValidationError as error:
        return None, str(error)
