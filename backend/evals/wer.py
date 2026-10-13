"""Word Error Rate between a reference and a hypothesis transcript.

    WER = (substitutions + deletions + insertions) / len(reference_words)

computed by aligning the two word sequences with word-level Levenshtein
edit distance - the standard ASR accuracy metric. This is a small,
dependency-free implementation rather than ``jiwer``: the algorithm is a
well-defined ~30-line dynamic program, and this avoids pinning another
package for a tool nothing at runtime imports. Normalization (``normalize``)
is deliberately simple and documented here, so a WER number is reproducible
and explainable without reading this file.

Usage (see backend/evals/README.md for the full recipe, including turning
your own audio into a hypothesis transcript with ``evals.transcribe_audio``)::

    python -m evals.wer reference.txt hypothesis.txt
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_PUNCTUATION_RE = re.compile(r"[^\w\s']")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize(text: str) -> list[str]:
    """Lowercase, drop punctuation (keeping apostrophes for contractions),
    collapse whitespace, and split into words."""
    text = _PUNCTUATION_RE.sub(" ", text.lower())
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text.split(" ") if text else []


@dataclass(frozen=True, slots=True)
class WERResult:
    substitutions: int
    deletions: int
    insertions: int
    reference_word_count: int

    @property
    def errors(self) -> int:
        return self.substitutions + self.deletions + self.insertions

    @property
    def wer(self) -> float:
        """1.0 = every reference word wrong; can exceed 1.0 with many insertions."""
        if self.reference_word_count == 0:
            return 0.0 if self.errors == 0 else float("inf")
        return self.errors / self.reference_word_count


def word_error_rate(reference: str, hypothesis: str) -> WERResult:
    return _align(normalize(reference), normalize(hypothesis))


def _align(ref: list[str], hyp: list[str]) -> WERResult:
    """Edit-distance DP with a backtrace, so each edit is classified as a
    substitution, deletion (a reference word missing from the hypothesis), or
    insertion (an extra hypothesis word) rather than just counted."""
    n, m = len(ref), len(hyp)
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])

    i, j = n, m
    substitutions = deletions = insertions = 0
    while i > 0 or j > 0:
        if i > 0 and j > 0 and ref[i - 1] == hyp[j - 1]:
            i, j = i - 1, j - 1
        elif i > 0 and j > 0 and dp[i][j] == dp[i - 1][j - 1] + 1:
            substitutions += 1
            i, j = i - 1, j - 1
        elif i > 0 and dp[i][j] == dp[i - 1][j] + 1:
            deletions += 1
            i -= 1
        else:
            insertions += 1
            j -= 1
    return WERResult(substitutions, deletions, insertions, n)


def _main() -> None:
    parser = argparse.ArgumentParser(
        description="Word Error Rate between a reference and a hypothesis transcript."
    )
    parser.add_argument("reference", type=Path, help="path to the reference (ground truth) text")
    parser.add_argument("hypothesis", type=Path, help="path to the hypothesis (ASR output) text")
    args = parser.parse_args()

    for path in (args.reference, args.hypothesis):
        if not path.exists():
            print(f"No such file: {path}", file=sys.stderr)
            sys.exit(1)

    result = word_error_rate(args.reference.read_text(), args.hypothesis.read_text())
    print(f"WER: {result.wer:.2%}")
    print(
        f"  substitutions={result.substitutions} deletions={result.deletions} "
        f"insertions={result.insertions} reference_words={result.reference_word_count}"
    )


if __name__ == "__main__":
    _main()
