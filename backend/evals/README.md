# AI insights & transcription evaluation

Offline tools for evaluating two things the running app produces: meeting
insights (`app/services/ai_service.py`, backed by Groq) and live transcripts
(`app/services/deepgram_service.py`, backed by Deepgram). Nothing here is
imported by the app; run it from `backend/` with the same venv as the tests
(`backend/.venv`).

## Insights eval

```bash
GROQ_API_KEY=... python -m evals.run_eval
GROQ_API_KEY=... python -m evals.run_eval --fixture evals/fixtures/orbitlytics-standup-01.json
```

Needs `GROQ_API_KEY` and makes real calls to Groq (one per fixture, plus a
retry for any fixture whose first reply isn't valid JSON - the same
one-retry policy `generate_insights` uses, with the same model, temperature,
token limit and reasoning effort; a test fails if those ever diverge from
production). Without the key, it prints a
clear message to stderr and exits 0 rather than failing - safe to leave out
of CI or a normal dev environment. It never runs from the test suite; the
scoring and orchestration logic is unit-tested with a fake model in
`tests/test_evals_run_eval.py`, `tests/test_evals_scoring.py`, and
`tests/test_evals_groq_client.py`.

Each run prints a summary and writes the full per-fixture report as JSON to
`evals/results/` (gitignored - regenerate instead of committing).
`--price-per-1m-prompt` / `--price-per-1m-completion` add an estimated
dollar cost per meeting-hour if you pass both; there's no built-in default,
since Groq's pricing changes and a stale hardcoded number would be worse
than no number.

### Fixtures (`evals/fixtures/*.json`)

20 synthetic meetings (fictional companies and people) across standups,
planning, incident reviews, sales calls, and 1:1s. Each file:

```jsonc
{
  "meeting_id": "orbitlytics-standup-01",   // must match the filename
  "meeting_type": "standup",                 // standup | planning | incident_review | sales_call | one_on_one
  "company": "Orbitlytics",
  "title": "...",
  "duration_minutes": 12,                    // nominal length, used for tokens-per-meeting-hour
  "participants": ["Priya Nandakumar", "..."],
  "transcript": [{"speaker": "...", "text": "..."}, "..."],
  "ground_truth": {
    "summary_key_points": ["..."],
    "action_items": [{"owner": "...", "task": "..."}],
    "decisions": ["..."],
    "open_questions": ["..."]
  }
}
```

`tests/test_evals_run_eval.py::test_all_shipped_fixtures_are_well_formed`
checks every fixture against this shape (and that action-item owners are
real participants), so a malformed fixture fails CI immediately.

### Metrics and matching rules (`evals/scoring.py`)

Production's `MeetingInsights.action_items` (and `decisions`,
`questions_raised`) are lists of free-text sentences, not structured
owner/task pairs - there's no separate owner field to compare directly.
Every rule below is intentionally simple enough to check by eye against a
real transcript, documented in one place rather than spread across code:

- **Action items** (precision / recall / F1): a predicted sentence matches
  an expected `{owner, task}` if (a) the owner's name appears anywhere in
  the sentence (`owners_match_in_text` - "Priya" matches "Priya Nandakumar"
  by shared name token) **and** (b) `difflib.SequenceMatcher` similarity
  between the full predicted sentence and the expected task is at least
  `TASK_SIMILARITY_THRESHOLD` (0.6, calibrated against paraphrase examples
  in `tests/test_evals_scoring.py`). Candidate matches are resolved with a
  **greedy** one-to-one assignment (highest similarity first) - not an
  optimal (Hungarian-algorithm) assignment, which would be overkill at the
  single-digit-to-low-dozens items per meeting this project deals with.
- **Decisions / open questions** (recall): same fuzzy text matching,
  without the owner check. Graded on recall per the brief - did the model
  surface what was actually decided or asked.
- **Summary key-point coverage**: a coarse, dependency-free heuristic - a
  key point counts as covered if at least 60% of its significant words
  (stopwords removed) appear somewhere in the model's summary. It won't
  credit a heavily-paraphrased summary that covers the same ground with
  different words; that's a deliberate trade for something simple enough to
  audit by hand.
- **Latency**: wall-clock time around the Groq call(s) for that meeting
  (including a retry, if one happened).
- **Token cost per meeting-hour**: `(prompt_tokens + completion_tokens)` for
  the meeting, normalized by `duration_minutes` and summed across the
  fixture set: `total_tokens / (total_duration_minutes / 60)`.

Every threshold is a module-level constant in `scoring.py` with a comment
explaining where the number came from - change it there, not in the tests.

## Word Error Rate (`evals/wer.py`)

```bash
python -m evals.wer reference.txt hypothesis.txt
```

A small, dependency-free word-level Levenshtein alignment (substitutions +
deletions + insertions, divided by the reference word count) - the standard
ASR accuracy metric. `jiwer` would do the same thing, but the algorithm is
short and well-defined enough that adding a pinned dependency for a
non-runtime tool didn't seem worth it; `normalize()`'s rules (lowercase,
strip punctuation, collapse whitespace) are documented in the module so a
WER number is reproducible without reading the code.

This repo ships no audio or transcript datasets. To run it on your own
recording:

1. Get a short audio file you have the rights to use (a real meeting
   recording, or anything you record yourself).
2. Write out the **reference** transcript - what was actually said - as a
   plain text file.
3. Produce a **hypothesis** transcript:
   ```bash
   DEEPGRAM_API_KEY=... python -m evals.transcribe_audio meeting.webm > hypothesis.txt
   ```
   This feeds your file through `DeepgramStreamer` - the same class the
   live backend streams browser audio through - in chunks, and joins the
   final results. Without `DEEPGRAM_API_KEY` it skips cleanly (exit 0); its
   chunking/collection logic is unit-tested with `FakeDeepgram` in
   `tests/test_evals_transcribe_audio.py`, so this doesn't call Deepgram
   from the test suite either. If you already have a hypothesis transcript
   from somewhere else (another ASR, a manual pass), skip this step.
4. Compare them:
   ```bash
   python -m evals.wer reference.txt hypothesis.txt
   ```
