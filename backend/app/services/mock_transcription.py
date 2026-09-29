"""Scripted transcription used when Deepgram is not configured (demo mode)."""

from __future__ import annotations

import asyncio
import random
from collections.abc import AsyncIterator

from app.services.transcription import TranscriptResult

# Realistic meeting dialogue - 20 sentences across four speakers.
DIALOGUE: tuple[tuple[str, str], ...] = (
    ("Alice", "Good morning everyone, let's get started with today's standup."),
    ("Bob", "Sure, I'll kick things off — I finished the API authentication layer yesterday."),
    (
        "Carol",
        "That's great news. I was blocked on that, so I can pick up the integration tests now.",
    ),
    (
        "David",
        "Before we dive in, can we quickly review the quarterly goals to make sure we're aligned?",
    ),
    ("Alice", "Absolutely. The main objective this quarter is to ship the v2 onboarding flow."),
    (
        "Bob",
        "I think we should also prioritize the API redesign — the current structure is causing "
        "friction.",
    ),
    (
        "Carol",
        "Agreed. The customer feedback has been mostly positive, but the auth flow gets "
        "mentioned a lot.",
    ),
    (
        "David",
        "Can everyone align on the timeline? I want to make sure we're not over-promising to "
        "stakeholders.",
    ),
    ("Alice", "Realistically, we're looking at three to four weeks for a polished beta."),
    (
        "Bob",
        "I can have the backend endpoints ready by end of next week if nothing unexpected comes "
        "up.",
    ),
    ("Carol", "I'll run the integration tests in parallel so we're not waiting on QA at the end."),
    (
        "David",
        "That sounds like a solid plan. Let's make sure we have daily check-ins to surface "
        "blockers early.",
    ),
    (
        "Alice",
        "One more thing — the design team flagged some accessibility issues in the dashboard.",
    ),
    (
        "Bob",
        "I saw that ticket. It's mostly color-contrast and keyboard navigation, shouldn't take "
        "long.",
    ),
    (
        "Carol",
        "I can pair with whoever owns the frontend component to get that sorted this sprint.",
    ),
    (
        "David",
        "Perfect. Let's also make sure the release notes are ready before we push to production.",
    ),
    ("Alice", "Agreed. I'll draft the release notes by Thursday and share them for review."),
    ("Bob", "Sounds good. I'll update the internal wiki with the new API docs at the same time."),
    (
        "Carol",
        "Is there anything else we need to cover before we break out into our separate tasks?",
    ),
    (
        "David",
        "I think that covers everything. Great discussion, team — let's ship a great product this "
        "quarter.",
    ),
)

# Multiplies every simulated delay; tests set it to 0.
PACE = 1.0
WORD_DELAY_SECONDS = (0.08, 0.25)
SENTENCE_PAUSE_SECONDS = (0.4, 1.2)
# Emit an interim result every N words, like a streaming recognizer would.
INTERIM_EVERY_WORDS = 4


class MockTranscriptionSource:
    """Replays ``DIALOGUE`` word by word, with interim and final results.

    ``start_index`` skips lines already delivered, so a reconnect continues the
    script instead of repeating it.
    """

    def __init__(self, start_index: int = 0) -> None:
        self._start_index = max(0, start_index)
        self._stop = asyncio.Event()

    @property
    def exhausted(self) -> bool:
        return self._start_index >= len(DIALOGUE)

    async def results(self) -> AsyncIterator[TranscriptResult]:
        elapsed = 0.0
        for speaker, sentence in DIALOGUE[self._start_index :]:
            words = sentence.split()
            started_at = elapsed
            for count in range(1, len(words) + 1):
                delay = random.uniform(*WORD_DELAY_SECONDS) * PACE
                if not await self._pause(delay):
                    return
                elapsed += delay
                if count < len(words) and count % INTERIM_EVERY_WORDS == 0:
                    yield TranscriptResult(
                        text=" ".join(words[:count]),
                        speaker="",
                        start=started_at,
                        confidence=round(random.uniform(0.6, 0.85), 4),
                        is_final=False,
                    )
            yield TranscriptResult(
                text=sentence,
                speaker=speaker,
                start=started_at,
                confidence=round(random.uniform(0.85, 0.99), 4),
                is_final=True,
            )
            pause = random.uniform(*SENTENCE_PAUSE_SECONDS) * PACE
            if not await self._pause(pause):
                return
            elapsed += pause

    async def send_audio(self, chunk: bytes) -> None:
        """The script ignores audio."""

    async def finish(self) -> None:
        self._stop.set()

    async def aclose(self) -> None:
        self._stop.set()

    async def _pause(self, seconds: float) -> bool:
        """Sleep for ``seconds``; return False if ``finish()`` was called meanwhile."""
        try:
            async with asyncio.timeout(seconds):
                await self._stop.wait()
        except TimeoutError:
            return True
        return False
