from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import settings
from evals import run_eval
from evals.run_eval import FixtureScore, evaluate_fixture, load_fixtures, summarize
from evals.scoring import PRF1, CoverageResult
from tests.fakes import FakeGroq

FIXTURE = {
    "meeting_id": "test-standup-01",
    "meeting_type": "standup",
    "company": "TestCo",
    "title": "Test Standup",
    "duration_minutes": 15,
    "participants": ["Priya Nandakumar", "Jae-won Lee"],
    "transcript": [
        {"speaker": "Priya Nandakumar", "text": "Let's get started with standup."},
        {"speaker": "Jae-won Lee", "text": "I'll finish the migration runbook today."},
    ],
    "ground_truth": {
        "summary_key_points": ["The team held their daily standup"],
        "action_items": [{"owner": "Jae-won Lee", "task": "Finish the migration runbook"}],
        "decisions": ["Ship the beta in four weeks"],
        "open_questions": ["Who owns QA for the rollout?"],
    },
}

REPLY = {
    "summary": "The team held their daily standup and reviewed progress.",
    "action_items": ["Jae-won will finish the migration runbook today."],
    "decisions": ["The team agreed to ship the beta within four weeks."],
    "questions_raised": ["Who will own QA for the rollout?"],
    "follow_up_email": "Subject: Standup notes\n\nThanks all.",
}


# --- main() skip-clean behavior ------------------------------------------------------


def test_main_skips_cleanly_without_groq_api_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(settings, "groq_api_key", "")

    with pytest.raises(SystemExit) as excinfo:
        run_eval.main()

    assert excinfo.value.code == 0
    assert "GROQ_API_KEY" in capsys.readouterr().err


# --- evaluate_fixture, with a fake model --------------------------------------------


async def test_evaluate_fixture_scores_a_good_reply() -> None:
    FakeGroq.reset(REPLY)
    client = FakeGroq()

    score = await evaluate_fixture(client, FIXTURE)

    assert score.meeting_id == "test-standup-01"
    assert score.action_items.f1 == 1.0
    assert score.decisions.recall == 1.0
    assert score.open_questions.recall == 1.0
    assert score.summary_coverage.coverage == 1.0
    assert score.latency_seconds >= 0
    assert score.prompt_tokens > 0
    assert score.completion_tokens > 0
    assert score.error is None


async def test_evaluate_fixture_handles_an_unusable_reply() -> None:
    FakeGroq.reset("not json", "still not json")
    client = FakeGroq()

    score = await evaluate_fixture(client, FIXTURE)

    # Nothing was predicted (content is None), so precision is vacuously 1.0
    # (no wrong guesses) but recall is 0.0 (nothing found) - see scoring._prf1.
    assert score.action_items == PRF1(1.0, 0.0, 0.0, 0, 0, 1)
    assert score.decisions.recall == 0.0
    assert score.summary_coverage == CoverageResult(0, 1)
    assert score.error is not None


# --- summarize() aggregation ---------------------------------------------------------


def test_summarize_aggregates_across_fixtures() -> None:
    scores = [
        FixtureScore(
            meeting_id="a",
            meeting_type="standup",
            action_items=PRF1(1.0, 1.0, 1.0, 1, 1, 1),
            decisions=PRF1(1.0, 1.0, 1.0, 1, 1, 1),
            open_questions=PRF1(1.0, 1.0, 1.0, 1, 1, 1),
            summary_coverage=CoverageResult(1, 1),
            latency_seconds=1.0,
            prompt_tokens=100,
            completion_tokens=50,
            duration_minutes=15,
            retried=False,
            error=None,
        ),
        FixtureScore(
            meeting_id="b",
            meeting_type="planning",
            action_items=PRF1(0.0, 0.0, 0.0, 0, 1, 1),
            decisions=PRF1(0.0, 0.0, 0.0, 0, 0, 1),
            open_questions=PRF1(1.0, 1.0, 1.0, 0, 0, 0),
            summary_coverage=CoverageResult(0, 2),
            latency_seconds=3.0,
            prompt_tokens=300,
            completion_tokens=100,
            duration_minutes=45,
            retried=True,
            error="model reply failed validation",
        ),
    ]

    report = summarize(scores)

    assert report["fixture_count"] == 2
    assert report["errors"] == 1
    assert report["retried"] == 1
    assert report["action_items"]["f1_mean"] == 0.5
    assert report["latency_seconds_mean"] == 2.0
    assert report["total_prompt_tokens"] == 400
    assert report["total_completion_tokens"] == 150
    # 550 tokens total over 60 minutes = 1 meeting-hour.
    assert report["tokens_per_meeting_hour"] == 550.0
    assert len(report["per_fixture"]) == 2


def test_summarize_empty_scores_does_not_divide_by_zero() -> None:
    report = summarize([])
    assert report["fixture_count"] == 0
    assert report["tokens_per_meeting_hour"] == 0.0


# --- fixtures on disk are well-formed -------------------------------------------------

VALID_MEETING_TYPES = {"standup", "planning", "incident_review", "sales_call", "one_on_one"}


def test_all_shipped_fixtures_are_well_formed() -> None:
    fixtures = load_fixtures()
    assert len(fixtures) >= 20

    seen_ids: set[str] = set()
    for fixture in fixtures:
        meeting_id = fixture["meeting_id"]
        assert meeting_id not in seen_ids, f"duplicate meeting_id {meeting_id}"
        seen_ids.add(meeting_id)

        assert fixture["meeting_type"] in VALID_MEETING_TYPES
        assert fixture["duration_minutes"] > 0
        assert fixture["participants"]
        assert len(fixture["transcript"]) >= 4

        for turn in fixture["transcript"]:
            assert turn["speaker"] in fixture["participants"]
            assert turn["text"].strip()

        gt = fixture["ground_truth"]
        assert gt["summary_key_points"]
        assert gt["action_items"]
        for item in gt["action_items"]:
            assert item["owner"] in fixture["participants"]
            assert item["task"].strip()


def test_fixture_files_match_their_meeting_ids() -> None:
    for path in (Path(__file__).parents[1] / "evals" / "fixtures").glob("*.json"):
        data = json.loads(path.read_text())
        assert path.stem == data["meeting_id"], f"{path.name} filename != meeting_id"
