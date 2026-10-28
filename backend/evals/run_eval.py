"""CLI: run the AI insights eval suite against real Groq, and score the results.

Makes real network calls, so it needs ``GROQ_API_KEY`` - it is never run from
the test suite (``tests/test_evals_run_eval.py`` covers this module's logic
with a fake client instead). Skips cleanly, with a clear message and exit
code 0, when the key is unset::

    GROQ_API_KEY=... python -m evals.run_eval
    GROQ_API_KEY=... python -m evals.run_eval --fixture fixtures/orbitlytics-standup-01.json

See backend/evals/README.md for the metrics and how to read the report.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from groq import AsyncGroq

from app.core.config import settings
from app.models.schemas import TranscriptSegment
from app.services.ai_service import build_transcript
from evals import scoring
from evals.groq_client import request_insights

FIXTURES_DIR = Path(__file__).parent / "fixtures"
RESULTS_DIR = Path(__file__).parent / "results"
# Fixtures don't carry real timing; segments only need a stable order for the
# prompt, so turns are spread out at a nominal pace.
SEGMENT_INTERVAL_SECONDS = 20.0


@dataclass(frozen=True, slots=True)
class FixtureScore:
    meeting_id: str
    meeting_type: str
    action_items: scoring.PRF1
    decisions: scoring.PRF1
    open_questions: scoring.PRF1
    summary_coverage: scoring.CoverageResult
    latency_seconds: float
    prompt_tokens: int
    completion_tokens: int
    duration_minutes: float
    retried: bool
    error: str | None


def load_fixtures(paths: list[Path] | None = None) -> list[dict]:
    files = paths if paths else sorted(FIXTURES_DIR.glob("*.json"))
    return [json.loads(p.read_text()) for p in files]


def _segments_for(fixture: dict) -> list[TranscriptSegment]:
    meeting_id = fixture["meeting_id"]
    return [
        TranscriptSegment(
            id=f"{meeting_id}-{i}",
            meeting_id=meeting_id,
            sequence=i + 1,
            speaker=turn["speaker"],
            text=turn["text"],
            timestamp=i * SEGMENT_INTERVAL_SECONDS,
            confidence=0.95,
        )
        for i, turn in enumerate(fixture["transcript"])
    ]


async def evaluate_fixture(client: AsyncGroq, fixture: dict) -> FixtureScore:
    segments = _segments_for(fixture)
    transcript_text, _ = build_transcript(segments, settings.ai_max_transcript_chars)
    result = await request_insights(client, fixture["title"], transcript_text)

    gt = fixture["ground_truth"]
    expected_items = [scoring.ActionItem(**item) for item in gt["action_items"]]
    content = result.content
    predicted_actions = content.action_items if content else []
    predicted_decisions = content.decisions if content else []
    predicted_questions = content.questions_raised if content else []
    predicted_summary = content.summary if content else ""

    return FixtureScore(
        meeting_id=fixture["meeting_id"],
        meeting_type=fixture["meeting_type"],
        action_items=scoring.score_action_items(predicted_actions, expected_items),
        decisions=scoring.score_recall(predicted_decisions, gt["decisions"]),
        open_questions=scoring.score_recall(predicted_questions, gt["open_questions"]),
        summary_coverage=scoring.score_summary_coverage(
            predicted_summary, gt["summary_key_points"]
        ),
        latency_seconds=result.latency_seconds,
        prompt_tokens=result.prompt_tokens,
        completion_tokens=result.completion_tokens,
        duration_minutes=fixture["duration_minutes"],
        retried=result.retried,
        error=result.error,
    )


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def summarize(scores: list[FixtureScore]) -> dict:
    total_minutes = sum(s.duration_minutes for s in scores)
    total_prompt = sum(s.prompt_tokens for s in scores)
    total_completion = sum(s.completion_tokens for s in scores)
    tokens_per_meeting_hour = (
        (total_prompt + total_completion) / (total_minutes / 60) if total_minutes else 0.0
    )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "fixture_count": len(scores),
        "errors": sum(1 for s in scores if s.error),
        "retried": sum(1 for s in scores if s.retried),
        "action_items": {
            "precision_mean": round(_mean([s.action_items.precision for s in scores]), 3),
            "recall_mean": round(_mean([s.action_items.recall for s in scores]), 3),
            "f1_mean": round(_mean([s.action_items.f1 for s in scores]), 3),
        },
        "decisions_recall_mean": round(_mean([s.decisions.recall for s in scores]), 3),
        "open_questions_recall_mean": round(_mean([s.open_questions.recall for s in scores]), 3),
        "summary_coverage_mean": round(_mean([s.summary_coverage.coverage for s in scores]), 3),
        "latency_seconds_mean": round(_mean([s.latency_seconds for s in scores]), 2),
        "total_prompt_tokens": total_prompt,
        "total_completion_tokens": total_completion,
        "tokens_per_meeting_hour": round(tokens_per_meeting_hour, 1),
        "per_fixture": [
            {
                "meeting_id": s.meeting_id,
                "meeting_type": s.meeting_type,
                "action_items_f1": round(s.action_items.f1, 3),
                "decisions_recall": round(s.decisions.recall, 3),
                "open_questions_recall": round(s.open_questions.recall, 3),
                "summary_coverage": round(s.summary_coverage.coverage, 3),
                "latency_seconds": round(s.latency_seconds, 2),
                "prompt_tokens": s.prompt_tokens,
                "completion_tokens": s.completion_tokens,
                "retried": s.retried,
                "error": s.error,
            }
            for s in scores
        ],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the AI insights eval suite against Groq.")
    parser.add_argument(
        "--fixture", action="append", type=Path, help="one fixture file (repeatable); default: all"
    )
    parser.add_argument(
        "--price-per-1m-prompt",
        type=float,
        default=None,
        help="USD per 1M prompt tokens, for an optional cost estimate (no default - "
        "check Groq's current pricing yourself rather than trust a hardcoded one)",
    )
    parser.add_argument("--price-per-1m-completion", type=float, default=None)
    parser.add_argument("--out", type=Path, default=None)
    return parser.parse_args()


async def _run(args: argparse.Namespace) -> dict:
    client = AsyncGroq(
        api_key=settings.groq_api_key, timeout=settings.groq_timeout_seconds, max_retries=1
    )
    try:
        fixtures = load_fixtures(args.fixture)
        scores = [await evaluate_fixture(client, fixture) for fixture in fixtures]
    finally:
        await client.close()

    report = summarize(scores)
    if args.price_per_1m_prompt is not None and args.price_per_1m_completion is not None:
        total_minutes = sum(s.duration_minutes for s in scores) or 60.0
        cost = (
            report["total_prompt_tokens"] / 1_000_000 * args.price_per_1m_prompt
            + report["total_completion_tokens"] / 1_000_000 * args.price_per_1m_completion
        )
        report["estimated_cost_usd_per_meeting_hour"] = round(cost / (total_minutes / 60), 4)
    return report


def _print_summary(report: dict) -> None:
    ai = report["action_items"]
    print(
        f"Evaluated {report['fixture_count']} fixtures "
        f"({report['errors']} errors, {report['retried']} retried)"
    )
    print(
        f"  action items:           P={ai['precision_mean']} R={ai['recall_mean']} "
        f"F1={ai['f1_mean']}"
    )
    print(f"  decisions recall:       {report['decisions_recall_mean']}")
    print(f"  open questions recall:  {report['open_questions_recall_mean']}")
    print(f"  summary coverage:       {report['summary_coverage_mean']}")
    print(f"  latency (s), mean:      {report['latency_seconds_mean']}")
    print(f"  tokens / meeting-hour:  {report['tokens_per_meeting_hour']}")
    if "estimated_cost_usd_per_meeting_hour" in report:
        print(f"  est. cost / meeting-hour: ${report['estimated_cost_usd_per_meeting_hour']}")


def main() -> None:
    if not settings.groq_api_key:
        print(
            "GROQ_API_KEY is not set; skipping the insights eval (it calls the real Groq API). "
            "Set it in your environment to run this.",
            file=sys.stderr,
        )
        sys.exit(0)

    args = _parse_args()
    report = asyncio.run(_run(args))
    _print_summary(report)

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = args.out or RESULTS_DIR / f"eval-{int(time.time())}.json"
    out_path.write_text(json.dumps(report, indent=2))
    print(f"\nFull report written to {out_path}")


if __name__ == "__main__":
    main()
