"""Test doubles for the external services (Groq, Deepgram, the mock script)."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, ClassVar

import httpx

from app.services.transcription import TranscriptionUnavailableError, TranscriptResult

VALID_INSIGHTS = {
    "summary": "The team agreed on the v2 onboarding timeline.",
    "action_items": ["Alice drafts the release notes"],
    "decisions": ["Ship a beta in four weeks"],
    "questions_raised": ["Who owns QA?"],
    "follow_up_email": "Subject: Standup follow-up\n\nThanks all.",
}

GROQ_REQUEST = httpx.Request("POST", "https://api.groq.com/openai/v1/chat/completions")


class FakeGroq:
    """Stands in for ``groq.AsyncGroq``: returns queued replies, records requests."""

    instances: ClassVar[list[FakeGroq]] = []
    replies: ClassVar[list[str | Exception]] = []

    def __init__(self, **options: Any) -> None:
        self.options = options
        self.requests: list[dict[str, Any]] = []
        self.closed = False
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        FakeGroq.instances.append(self)

    @classmethod
    def reset(cls, *replies: str | Exception | dict[str, Any]) -> None:
        cls.instances.clear()
        cls.replies[:] = [json.dumps(r) if isinstance(r, dict) else r for r in replies]

    @classmethod
    def requests_made(cls) -> list[dict[str, Any]]:
        return [request for client in cls.instances for request in client.requests]

    async def _create(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        reply = FakeGroq.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        message = SimpleNamespace(content=reply)
        # A deterministic chars/4 stand-in for token counts (real usage isn't
        # inspected by ai_service, only by the eval harness's own tests).
        prompt_chars = sum(len(m.get("content", "")) for m in request.get("messages", []))
        usage = SimpleNamespace(
            prompt_tokens=prompt_chars // 4,
            completion_tokens=len(reply) // 4 if isinstance(reply, str) else 0,
        )
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)

    async def close(self) -> None:
        self.closed = True


def final(text: str, speaker: str = "Alice", start: float = 0.0) -> TranscriptResult:
    return TranscriptResult(text=text, speaker=speaker, start=start, confidence=0.9, is_final=True)


def interim(text: str, start: float = 0.0) -> TranscriptResult:
    return TranscriptResult(text=text, speaker="", start=start, confidence=0.5, is_final=False)


class ScriptedSource:
    """Replaces the mock script: yields ``script`` once released, then waits.

    ``results()`` ends when the session calls ``finish()`` (like a flushed
    Deepgram stream), so tests control exactly when a source completes.
    """

    instances: ClassVar[list[ScriptedSource]] = []
    script: ClassVar[list[TranscriptResult]] = []
    auto_release: ClassVar[bool] = True
    complete_after_script: ClassVar[bool] = False

    def __init__(self, start_index: int = 0) -> None:
        self.start_index = start_index
        self.released = asyncio.Event()
        self.finished = asyncio.Event()
        if ScriptedSource.auto_release:
            self.released.set()
        ScriptedSource.instances.append(self)

    @classmethod
    def reset(
        cls, *script: TranscriptResult, auto_release: bool = True, complete: bool = False
    ) -> None:
        cls.instances.clear()
        cls.script = list(script)
        cls.auto_release = auto_release
        cls.complete_after_script = complete

    exhausted = False

    async def results(self) -> AsyncIterator[TranscriptResult]:
        await self.released.wait()
        for result in ScriptedSource.script:
            yield result
        if not ScriptedSource.complete_after_script:
            await self.finished.wait()

    async def send_audio(self, chunk: bytes) -> None:
        return None

    async def finish(self) -> None:
        self.finished.set()

    async def aclose(self) -> None:
        self.finished.set()


class FakeDeepgram:
    """Stands in for ``DeepgramStreamer``: each audio frame yields one final result."""

    instances: ClassVar[list[FakeDeepgram]] = []
    fail_connect: ClassVar[bool] = False

    def __init__(self, api_key: str, **_: Any) -> None:
        self.api_key = api_key
        self.audio: list[bytes] = []
        self.finished = False
        self._results: asyncio.Queue[TranscriptResult | None] = asyncio.Queue()
        FakeDeepgram.instances.append(self)

    @classmethod
    def reset(cls, *, fail_connect: bool = False) -> None:
        cls.instances.clear()
        cls.fail_connect = fail_connect

    async def connect(self) -> None:
        if FakeDeepgram.fail_connect:
            raise TranscriptionUnavailableError("Deepgram refused the connection (HTTP 401)")

    async def send_audio(self, chunk: bytes) -> None:
        self.audio.append(chunk)
        self._results.put_nowait(interim(f"heard {len(self.audio)}"))

    async def finish(self) -> None:
        # Like CloseStream: the last buffered words arrive as a final result.
        self.finished = True
        self._results.put_nowait(final(f"final words after {len(self.audio)} frames", "Speaker 1"))
        self._results.put_nowait(None)

    async def results(self) -> AsyncIterator[TranscriptResult]:
        while (result := await self._results.get()) is not None:
            yield result

    async def aclose(self) -> None:
        self._results.put_nowait(None)
