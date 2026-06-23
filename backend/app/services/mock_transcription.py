import asyncio
import random
import uuid
from typing import AsyncGenerator

from app.models.schemas import TranscriptSegment

# ---------------------------------------------------------------------------
# Realistic meeting dialogue — 20 sentences across four speakers
# ---------------------------------------------------------------------------

_DIALOGUE: list[tuple[str, str]] = [
    ("Alice", "Good morning everyone, let's get started with today's standup."),
    ("Bob", "Sure, I'll kick things off — I finished the API authentication layer yesterday."),
    ("Carol", "That's great news. I was blocked on that, so I can pick up the integration tests now."),
    ("David", "Before we dive in, can we quickly review the quarterly goals to make sure we're aligned?"),
    ("Alice", "Absolutely. The main objective this quarter is to ship the v2 onboarding flow."),
    ("Bob", "I think we should also prioritize the API redesign — the current structure is causing friction."),
    ("Carol", "Agreed. The customer feedback has been mostly positive, but the auth flow gets mentioned a lot."),
    ("David", "Can everyone align on the timeline? I want to make sure we're not over-promising to stakeholders."),
    ("Alice", "Realistically, we're looking at three to four weeks for a polished beta."),
    ("Bob", "I can have the backend endpoints ready by end of next week if nothing unexpected comes up."),
    ("Carol", "I'll run the integration tests in parallel so we're not waiting on QA at the end."),
    ("David", "That sounds like a solid plan. Let's make sure we have daily check-ins to surface blockers early."),
    ("Alice", "One more thing — the design team flagged some accessibility issues in the dashboard."),
    ("Bob", "I saw that ticket. It's mostly color-contrast and keyboard navigation, shouldn't take long."),
    ("Carol", "I can pair with whoever owns the frontend component to get that sorted this sprint."),
    ("David", "Perfect. Let's also make sure the release notes are ready before we push to production."),
    ("Alice", "Agreed. I'll draft the release notes by Thursday and share them for review."),
    ("Bob", "Sounds good. I'll update the internal wiki with the new API docs at the same time."),
    ("Carol", "Is there anything else we need to cover before we break out into our separate tasks?"),
    ("David", "I think that covers everything. Great discussion, team — let's ship a great product this quarter."),
]

# ---------------------------------------------------------------------------
# Async generator
# ---------------------------------------------------------------------------


async def mock_transcript_stream(
    meeting_id: str,
) -> AsyncGenerator[TranscriptSegment, None]:
    """
    Yield TranscriptSegment objects with simulated word-by-word delays,
    mimicking the feel of a live transcription feed.

    Each sentence is broken into short "partial" reveals. We yield one
    segment per sentence so the caller keeps state simple, but we introduce
    realistic inter-word and inter-sentence pauses along the way.
    """
    elapsed: float = 0.0  # virtual clock — seconds from meeting start

    for speaker, full_text in _DIALOGUE:
        words = full_text.split()
        accumulated = ""

        for i, word in enumerate(words):
            # Simulate streaming word by word
            inter_word_delay = random.uniform(0.08, 0.25)
            await asyncio.sleep(inter_word_delay)
            elapsed += inter_word_delay
            accumulated += ("" if i == 0 else " ") + word

        # Yield the completed sentence as a single segment
        segment = TranscriptSegment(
            id=str(uuid.uuid4()),
            meeting_id=meeting_id,
            speaker=speaker,
            text=accumulated,
            timestamp=round(elapsed, 2),
            confidence=round(random.uniform(0.85, 0.99), 4),
        )
        yield segment

        # Natural pause between sentences (think-time / speaker change)
        pause = random.uniform(0.4, 1.2)
        await asyncio.sleep(pause)
        elapsed += pause
