from __future__ import annotations

import pytest

from evals.wer import normalize, word_error_rate


def test_normalize_lowercases_strips_punctuation_and_collapses_whitespace() -> None:
    assert normalize("Hello,  World! It's  great.") == ["hello", "world", "it's", "great"]


def test_normalize_empty_string() -> None:
    assert normalize("   ") == []


def test_identical_transcripts_have_zero_wer() -> None:
    result = word_error_rate("the quick brown fox", "the quick brown fox")
    assert result.wer == 0.0
    assert (result.substitutions, result.deletions, result.insertions) == (0, 0, 0)


def test_one_substitution() -> None:
    result = word_error_rate("the quick brown fox", "the fast brown fox")
    assert (result.substitutions, result.deletions, result.insertions) == (1, 0, 0)
    assert result.wer == pytest.approx(0.25)


def test_one_deletion() -> None:
    # hypothesis is missing "quick": one reference word wasn't produced.
    result = word_error_rate("the quick brown fox", "the brown fox")
    assert (result.substitutions, result.deletions, result.insertions) == (0, 1, 0)
    assert result.wer == pytest.approx(0.25)


def test_one_insertion() -> None:
    # hypothesis has an extra word not in the reference.
    result = word_error_rate("the quick brown fox", "the quick very brown fox")
    assert (result.substitutions, result.deletions, result.insertions) == (0, 0, 1)
    assert result.wer == pytest.approx(0.25)


def test_case_and_punctuation_do_not_count_as_errors() -> None:
    result = word_error_rate("The quick, brown fox.", "the quick brown fox")
    assert result.wer == 0.0


def test_completely_different_transcripts() -> None:
    result = word_error_rate("hello there", "goodbye now")
    assert result.substitutions == 2
    assert result.wer == 1.0


def test_empty_reference_and_empty_hypothesis() -> None:
    result = word_error_rate("", "")
    assert result.reference_word_count == 0
    assert result.wer == 0.0


def test_empty_reference_with_extra_hypothesis_words_is_infinite() -> None:
    result = word_error_rate("", "hello")
    assert result.reference_word_count == 0
    assert result.wer == float("inf")


def test_empty_hypothesis_is_all_deletions() -> None:
    result = word_error_rate("the quick brown fox", "")
    assert result.deletions == 4
    assert result.wer == 1.0
