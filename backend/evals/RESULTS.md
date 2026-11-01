# Insights eval results

First runs of `python -m evals.run_eval` against real Groq. The JSON
reports are in `evals/results/` (gitignored); the numbers below are copied
from their summaries.

## Setup

- Date: 2026-11-01
- Commit: `4ab018e` (the harness fix that retries Groq `json_validate_failed`
  rejections the way `generate_insights` does)
- Model and options: production defaults from `app/core/config.py` -
  `openai/gpt-oss-120b`, temperature 0.3, `max_tokens` 4096, reasoning
  effort `low`, JSON mode, 30 s timeout, 1 client retry
- Fixtures: the 20 synthetic meetings in `evals/fixtures/`
- Groq free tier; MacBook Air M3, from `backend/`:

```bash
.venv/bin/python -m evals.run_eval --price-per-1m-prompt 0.15 --price-per-1m-completion 0.60
```

Prices are Groq's listed $0.15 / $0.60 per million input / output tokens
for `openai/gpt-oss-120b` (console.groq.com model page, checked 2026-11-01).

## Results

| Metric (mean over 20 fixtures) | Run A | Run B |
| --- | --- | --- |
| Action items precision | 0.345 | 0.377 |
| Action items recall | 0.392 | 0.332 |
| Action items F1 | 0.332 | 0.296 |
| Decisions recall | 0.275 | 0.275 |
| Open questions recall | 0.50 | 0.45 |
| Summary key-point coverage | 0.237 | 0.188 |
| Latency per meeting, mean | 2.74 s | 3.56 s |
| Tokens per meeting-hour | 3,624 | 3,516 |
| Estimated cost per meeting-hour | $0.0012 | $0.0011 |
| Fixtures with no usable reply | 1 | 2 |
| Fixtures retried after a bad reply | 1 | 0 |

Every fixture with no usable reply was a Groq free-tier 429 (tokens per
minute), not a model failure. In run A, `brightpath-standup-01` got a
`json_validate_failed` rejection and recovered on the retry; before
`4ab018e` the harness counted that as an error.

## How to read these numbers

- **The matcher undercounts.** Matching is lexical (`difflib` similarity
  ≥ 0.6 plus an owner-name check; see `README.md`), so correct paraphrases
  miss. Example from `orbitlytics-standup-01`: the model wrote "Jae-won will
  add Retry-After details to the documentation today" for the expected
  "Document the Retry-After header for the frontend team", which scores as a
  miss. Treat these as a lower bound on quality, not as the user-visible
  accuracy, and don't quote them without that caveat.
- **Run-to-run spread is large.** Temperature 0.3 and 20 short meetings
  move action-item F1 by about 0.04 between identical runs.
- **Errors count against the mean.** A fixture with no reply scores recall
  0, and precision 1.0 by convention (nothing predicted); with 1-2 such
  fixtures per run this slightly raises mean precision.

## Next

- A paraphrase-tolerant matcher (an LLM judge or embedding similarity,
  checked against hand labels) so the metric measures the model rather than
  wording.
- Pace requests under the free-tier tokens-per-minute limit so no fixture is
  lost to a 429.
