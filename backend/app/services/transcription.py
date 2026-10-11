"""Types shared by the transcription sources (Deepgram and the scripted mock)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


class TranscriptionUnavailableError(Exception):
    """The speech-to-text provider could not be reached or dropped the stream."""


@dataclass(frozen=True, slots=True)
class TranscriptResult:
    """One recognition result, before it is numbered and stored."""

    text: str
    speaker: str
    start: float  # seconds since the source started
    confidence: float
    is_final: bool


class TranscriptionSource(Protocol):
    def results(self) -> AsyncIterator[TranscriptResult]:
        """Yield results until the source finishes.

        Raises ``TranscriptionUnavailableError`` if the stream ends abnormally.
        """
        ...

    async def send_audio(self, chunk: bytes) -> None: ...

    async def finish(self) -> None:
        """Ask the source to flush pending results; ``results()`` then ends."""
        ...

    async def aclose(self) -> None:
        """Release resources immediately, dropping anything not yet flushed."""
        ...
