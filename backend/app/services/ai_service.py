import json
import uuid
import logging
from datetime import datetime, timezone
from groq import AsyncGroq
from app.core.config import settings
from app.models.schemas import MeetingInsights, TranscriptSegment

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are an expert meeting analyst. Given a meeting transcript, extract structured insights.
Return ONLY valid JSON with exactly these fields:
{
  "summary": "2-3 sentence paragraph summarizing the meeting",
  "action_items": ["action item 1", "action item 2", ...],
  "decisions": ["decision 1", "decision 2", ...],
  "questions_raised": ["question 1", "question 2", ...],
  "follow_up_email": "A professional follow-up email draft with subject line and body"
}
Be specific and concise. If a category has no items, return an empty array."""


async def generate_insights(
    meeting_id: str,
    meeting_title: str,
    segments: list[TranscriptSegment],
) -> MeetingInsights:
    if not settings.groq_api_key:
        raise ValueError("GROQ_API_KEY not configured")

    if not segments:
        raise ValueError("No transcript segments to analyze")

    # Build transcript text from final segments only
    transcript_lines = []
    for seg in segments:
        if seg.is_final:
            minutes = int(seg.timestamp // 60)
            seconds = int(seg.timestamp % 60)
            transcript_lines.append(f"[{minutes:02d}:{seconds:02d}] {seg.speaker}: {seg.text}")

    transcript_text = "\n".join(transcript_lines)

    user_prompt = f"""Meeting Title: {meeting_title}

Transcript:
{transcript_text}

Analyze this meeting and return the JSON insights."""

    client = AsyncGroq(api_key=settings.groq_api_key)

    logger.info("[AI] Generating insights for meeting %s (%d segments)", meeting_id, len(segments))

    response = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.3,
        max_tokens=2048,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    logger.info("[AI] Received response from Groq")

    data = json.loads(raw)

    return MeetingInsights(
        id=str(uuid.uuid4()),
        meeting_id=meeting_id,
        summary=data.get("summary", ""),
        action_items=data.get("action_items", []),
        decisions=data.get("decisions", []),
        questions_raised=data.get("questions_raised", []),
        follow_up_email=data.get("follow_up_email", ""),
        generated_at=datetime.now(timezone.utc),
    )
