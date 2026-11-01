from __future__ import annotations

from evals.scoring import (
    TASK_SIMILARITY_THRESHOLD,
    ActionItem,
    key_point_covered,
    owners_match,
    owners_match_in_text,
    score_action_items,
    score_recall,
    score_summary_coverage,
    text_similarity,
)

# --- Name / owner matching --------------------------------------------------------


def test_owners_match_on_first_name_only() -> None:
    assert owners_match("Priya", "Priya Nandakumar")
    assert owners_match("Priya Nandakumar", "P. Nandakumar")


def test_owners_match_is_case_and_punctuation_insensitive() -> None:
    assert owners_match("priya nandakumar", "Priya, Nandakumar!")


def test_owners_do_not_match_unrelated_names() -> None:
    assert not owners_match("Priya Nandakumar", "Jae-won Lee")


def test_owners_match_in_text_finds_the_name_inside_a_sentence() -> None:
    assert owners_match_in_text("Priya will finish the rollout by Friday.", "Priya Nandakumar")
    assert not owners_match_in_text(
        "Jae-won will finish the rollout by Friday.", "Priya Nandakumar"
    )


# --- Fuzzy text similarity (calibration) --------------------------------------------


def test_paraphrases_score_above_threshold() -> None:
    a = "Finish the API rate limiter rollout by Friday"
    b = "Priya will finish the API rate limiter rollout by Friday"
    assert text_similarity(a, b) >= TASK_SIMILARITY_THRESHOLD


def test_unrelated_sentences_score_below_threshold() -> None:
    a = "Finish the API rate limiter rollout by Friday"
    b = "Investigate the flaky checkout integration test"
    assert text_similarity(a, b) < TASK_SIMILARITY_THRESHOLD


# --- Action items ------------------------------------------------------------------


def test_action_items_perfect_match() -> None:
    expected = [
        ActionItem(owner="Priya Nandakumar", task="Finish the API rate limiter rollout by Friday"),
        ActionItem(owner="Jae-won Lee", task="Write the migration runbook"),
    ]
    predicted = [
        "Priya will finish the API rate limiter rollout by Friday.",
        "Jae-won to write the migration runbook.",
    ]
    result = score_action_items(predicted, expected)
    assert (result.matched, result.precision, result.recall, result.f1) == (2, 1.0, 1.0, 1.0)


def test_action_items_wrong_owner_does_not_match_even_with_similar_task() -> None:
    expected = [ActionItem(owner="Priya Nandakumar", task="Finish the rate limiter rollout")]
    predicted = ["Jae-won will finish the rate limiter rollout."]
    result = score_action_items(predicted, expected)
    assert result.matched == 0
    assert result.recall == 0.0


def test_action_items_right_owner_unrelated_task_does_not_match() -> None:
    expected = [ActionItem(owner="Priya Nandakumar", task="Finish the rate limiter rollout")]
    predicted = ["Priya will review the design doc for the new pricing page."]
    result = score_action_items(predicted, expected)
    assert result.matched == 0


def test_action_items_partial_credit() -> None:
    expected = [
        ActionItem(owner="Priya Nandakumar", task="Finish the API rate limiter rollout by Friday"),
        ActionItem(owner="Jae-won Lee", task="Write the migration runbook"),
    ]
    predicted = [
        "Priya will finish the API rate limiter rollout by Friday.",
        "Tomasz will look into the flaky integration test.",  # unmatched extra
    ]
    result = score_action_items(predicted, expected)
    assert result.matched == 1
    assert result.precision == 0.5  # 1 of 2 predictions matched
    assert result.recall == 0.5  # 1 of 2 expected items found


def test_action_items_greedy_matching_does_not_double_count() -> None:
    """Two predictions that could both match the same expected item only count once."""
    expected = [ActionItem(owner="Priya Nandakumar", task="Finish the rate limiter rollout")]
    predicted = [
        "Priya will finish the rate limiter rollout.",
        "Priya to finish the rate limiter rollout by Friday.",
    ]
    result = score_action_items(predicted, expected)
    assert result.matched == 1
    assert result.precision == 0.5
    assert result.recall == 1.0


def test_action_items_empty_predicted_and_empty_expected_is_perfect() -> None:
    result = score_action_items([], [])
    assert (result.precision, result.recall, result.f1) == (1.0, 1.0, 1.0)


def test_action_items_empty_predicted_against_expected_is_zero_recall() -> None:
    expected = [ActionItem(owner="Priya Nandakumar", task="Finish the rollout")]
    result = score_action_items([], expected)
    assert (result.precision, result.recall, result.f1) == (1.0, 0.0, 0.0)


def test_action_items_predicted_against_empty_expected_is_zero_precision() -> None:
    result = score_action_items(["Priya will finish the rollout."], [])
    assert (result.precision, result.recall, result.f1) == (0.0, 1.0, 0.0)


# --- Decisions / open questions (recall) --------------------------------------------


def test_score_recall_matches_paraphrases() -> None:
    expected = ["Ship the beta in four weeks", "Use PostgreSQL instead of DynamoDB"]
    predicted = ["The team will ship the beta within four weeks."]
    result = score_recall(predicted, expected)
    assert result.matched == 1
    assert result.recall == 0.5


def test_score_recall_with_nothing_predicted() -> None:
    result = score_recall([], ["Ship the beta in four weeks"])
    assert result.recall == 0.0


# --- Summary coverage ----------------------------------------------------------------


def test_key_point_covered_by_matching_words() -> None:
    summary = "The team agreed to ship the v2 onboarding flow within four weeks."
    assert key_point_covered("Ship the v2 onboarding flow", summary)


def test_key_point_not_covered_when_words_are_missing() -> None:
    summary = "The team discussed the quarterly roadmap and design review."
    assert not key_point_covered("Ship the v2 onboarding flow", summary)


def test_summary_coverage_ratio() -> None:
    summary = "The team agreed to ship the v2 onboarding flow within four weeks."
    key_points = [
        "Ship the v2 onboarding flow",
        "Fix the accessibility issues in the dashboard",
    ]
    result = score_summary_coverage(summary, key_points)
    assert (result.covered, result.total) == (1, 2)
    assert result.coverage == 0.5


def test_summary_coverage_with_no_key_points_is_perfect() -> None:
    result = score_summary_coverage("Anything.", [])
    assert result.coverage == 1.0
