"""Scoring AI-generated meeting insights against hand-written ground truth.

Every matching rule here is deliberately simple and documented rather than a
learned or semantic metric: this project's fixture set is small enough to
eyeball, so a transparent, debuggable rule that a human can double-check
beats a fancier one nobody can audit by hand.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

TASK_SIMILARITY_THRESHOLD = 0.6
"""``difflib.SequenceMatcher`` ratio, on normalized text, at or above which two
action items / decisions / open questions count as the same one. Calibrated
by eye against this project's fixtures (see ``tests/test_evals_scoring.py``):
paraphrases of the same sentence typically land at 0.6-0.9; unrelated
sentences typically land well under 0.4."""

SUMMARY_COVERAGE_WORD_THRESHOLD = 0.6
"""Fraction of a key point's significant words that must appear in the
model's summary for that point to count as covered."""

_STOPWORDS = frozenset([
    "the", "a", "an", "to", "of", "and", "in", "on", "for", "with", "is", "are",
    "was", "were", "be", "been", "being", "that", "this", "it", "as", "by", "at",
    "we", "us", "our", "their", "them", "its", "into", "from", "or", "so", "than",
    "then", "not", "no", "do", "does", "did", "has", "have", "had", "can", "could",
    "should", "would", "about", "up", "out", "if", "but", "they", "he", "she",
    "you", "your", "i", "also", "which", "who", "what", "when", "where", "will",
    "just",
])  # fmt: skip


# --- Text normalization ----------------------------------------------------------


def _normalize_text(text: str) -> str:
    """Lowercase, drop punctuation, collapse whitespace."""
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", text.lower())).strip()


def normalize_owner(name: str) -> frozenset[str]:
    """The set of name tokens in ``name``, lowercased. See ``owners_match``."""
    return frozenset(_normalize_text(name).split())


def owners_match(a: str, b: str) -> bool:
    """True if ``a`` and ``b`` share at least one name token.

    Catches the common real cases ("Priya" vs "Priya Nandakumar", "P.
    Nandakumar" vs "Priya Nandakumar") without needing a name database. It
    will also match two *different* people who happen to share a first name;
    fixtures in this project avoid that ambiguity by using distinct names.
    """
    left, right = normalize_owner(a), normalize_owner(b)
    return bool(left and right and (left & right))


def text_similarity(a: str, b: str) -> float:
    """``SequenceMatcher`` ratio in [0, 1] on normalized text."""
    return SequenceMatcher(None, _normalize_text(a), _normalize_text(b)).ratio()


# --- Precision / recall / F1 ------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PRF1:
    precision: float
    recall: float
    f1: float
    matched: int
    predicted: int
    expected: int


def _prf1(matched: int, predicted: int, expected: int) -> PRF1:
    # Convention: an empty prediction against an empty expectation is a
    # perfect (vacuous) score; an empty prediction against a non-empty
    # expectation is 0 recall (nothing found) but "precise" (no wrong
    # guesses), and vice versa.
    precision = 1.0 if predicted == 0 else matched / predicted
    recall = 1.0 if expected == 0 else matched / expected
    f1 = 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)
    return PRF1(precision, recall, f1, matched, predicted, expected)


def _greedy_match(candidates: list[tuple[float, int, int]]) -> int:
    """Given (score, predicted_index, expected_index) candidates, count a
    greedy one-to-one matching taken in descending score order.

    Not an optimal assignment (that would need the Hungarian algorithm) -
    greedy is simple, deterministic, and good enough at this project's scale
    (single-digit to low-dozens of items per meeting).
    """
    candidates = sorted(candidates, key=lambda c: c[0], reverse=True)
    used_predicted: set[int] = set()
    used_expected: set[int] = set()
    matched = 0
    for _, pi, ei in candidates:
        if pi in used_predicted or ei in used_expected:
            continue
        used_predicted.add(pi)
        used_expected.add(ei)
        matched += 1
    return matched


# --- Action items ------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ActionItem:
    """Ground truth is structured (we write it); the model's output isn't -
    ``MeetingInsights.action_items`` is a list of free-text sentences like
    "Alice will draft the release notes by Thursday", with no separate owner
    field. So matching can't compare two ``owner`` fields directly; instead
    it checks whether the expected owner's name appears anywhere in the
    predicted sentence (``owners_match_in_text``)."""

    owner: str
    task: str


def owners_match_in_text(predicted_text: str, owner: str) -> bool:
    """True if any of ``owner``'s name tokens appears in ``predicted_text``."""
    predicted_tokens = set(_normalize_text(predicted_text).split())
    owner_tokens = normalize_owner(owner)
    return bool(owner_tokens and (predicted_tokens & owner_tokens))


def score_action_items(predicted: list[str], expected: list[ActionItem]) -> PRF1:
    """Match by the expected owner's name appearing in the predicted sentence
    (``owners_match_in_text``) AND fuzzy similarity between the full predicted
    sentence and the expected task (``text_similarity`` >=
    ``TASK_SIMILARITY_THRESHOLD``), both required. The owner's name is
    usually only a couple of words within a longer sentence, so it barely
    affects the similarity ratio either way.
    """
    candidates = [
        (score, pi, ei)
        for pi, p in enumerate(predicted)
        for ei, e in enumerate(expected)
        if owners_match_in_text(p, e.owner)
        and (score := text_similarity(p, e.task)) >= TASK_SIMILARITY_THRESHOLD
    ]
    matched = _greedy_match(candidates)
    return _prf1(matched, len(predicted), len(expected))


# --- Decisions / open questions (text-only recall) ---------------------------------


def score_recall(predicted: list[str], expected: list[str]) -> PRF1:
    """Same greedy fuzzy matching as action items, without the owner check.

    Decisions and open questions are graded on recall in the brief (did the
    model surface what was actually decided/asked); precision is computed
    too since it falls out of the same matching for free, but recall is the
    headline number for these two.
    """
    candidates = [
        (text_similarity(p, e), pi, ei)
        for pi, p in enumerate(predicted)
        for ei, e in enumerate(expected)
        if text_similarity(p, e) >= TASK_SIMILARITY_THRESHOLD
    ]
    matched = _greedy_match(candidates)
    return _prf1(matched, len(predicted), len(expected))


# --- Summary key-point coverage -----------------------------------------------------


def _significant_words(text: str) -> set[str]:
    return {w for w in _normalize_text(text).split() if len(w) > 2 and w not in _STOPWORDS}


def key_point_covered(point: str, summary: str) -> bool:
    """Whether ``summary`` mentions enough of ``point``'s significant words.

    A coarse, conservative word-overlap check, not a semantic one: it won't
    give credit for a summary that paraphrases a key point with entirely
    different words. That's a deliberate trade for a metric that's simple,
    dependency-free, and easy to sanity-check by eye.
    """
    words = _significant_words(point)
    if not words:
        return False
    summary_words = set(_normalize_text(summary).split())
    hits = sum(1 for w in words if w in summary_words)
    return hits / len(words) >= SUMMARY_COVERAGE_WORD_THRESHOLD


@dataclass(frozen=True, slots=True)
class CoverageResult:
    covered: int
    total: int

    @property
    def coverage(self) -> float:
        return 1.0 if self.total == 0 else self.covered / self.total


def score_summary_coverage(summary: str, key_points: list[str]) -> CoverageResult:
    covered = sum(1 for point in key_points if key_point_covered(point, summary))
    return CoverageResult(covered, len(key_points))
