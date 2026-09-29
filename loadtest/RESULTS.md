# Load test results

**Date:** 2026-09-29
**Commit:** `d0beda3` (feat(api): make the create-meeting rate limit configurable)
**Machine:** MacBook Air, Apple M3, 8 GB RAM, macOS 26.5.2. Backend run natively
(not in Docker) in `backend/.venv` (Python 3.11.15); PostgreSQL 16 and Redis 7
in Docker, on non-default ports to avoid other local services.
**Mode:** `MOCK_TRANSCRIPTION=true` (scripted transcript, no Deepgram calls).
**Load generator:** `loadtest/wsload`, run from the `loadtest/` directory,
against the backend and load generator sharing this one machine — see the
caveats in `loadtest/README.md` before comparing these numbers to anything
else.

## Setup used for every run below

```bash
docker run -d --rm --name mse-postgres -e POSTGRES_PASSWORD=postgres -p 5434:5432 postgres:16
docker run -d --rm --name mse-redis -p 6381:6379 redis:7

cd backend
MOCK_TRANSCRIPTION=true \
DATABASE_URL="postgresql://postgres:postgres@localhost:5434/meetsense_test" \
REDIS_URL="redis://localhost:6381" \
ALLOW_MEMORY_FALLBACK=false \
WS_MAX_CONNECTIONS_PER_IP=500 \
CREATE_MEETING_RATE_LIMIT=1000/minute \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning &
# backend pid for this session: 50688
```

## Scenario (a): ramp — 10 -> 50 -> 100 -> 200 concurrent meetings

```bash
cd loadtest
../backend/.venv/bin/python -m wsload.run ramp \
  --stages 10,50,100,200 --stage-hold 20 --server-pid 50688 --out results/ramp-run1.json
```

One streaming socket per meeting, each sending a 1000-byte frame every 250ms.
Ran 02:14:47 -> 02:16:08 UTC (80.9s). All 200 connections opened; all closed
`1000` (clean); zero `error` frames; **2099 final transcript segments
received, 0 sequence gaps, 0 duplicates**, across every stage.

| stage | metric | n | p50 | p95 | p99 | max | mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10  | connect_ms            | 10   | 6.8   | 7.6   | 7.7   | 7.7  | 6.8   |
| 10  | connected_ms          | 10   | 47.8  | 63.7  | 64.0  | 64.1 | 47.0  |
| 10  | ping_rtt_ms           | 60   | 1.4   | 3.7   | 4.2   | 4.4  | 1.6   |
| 10  | transcript_latency_ms | 251  | 1.2   | 3.3   | 5.7   | 16.6 | 1.5   |
| 50  | connect_ms            | 40   | 16.4  | 20.3  | 21.0  | 21.3 | 16.5  |
| 50  | connected_ms          | 40   | 124.6 | 142.8 | 144.8 | 145.1| 124.9 |
| 50  | ping_rtt_ms           | 310  | 1.4   | 4.1   | 4.3   | 4.4  | 1.7   |
| 50  | transcript_latency_ms | 1247 | 0.8   | 2.6   | 8.3   | 39.0 | 1.1   |
| 100 | connect_ms            | 50   | 16.9  | 21.3  | 21.7  | 21.7 | 17.4  |
| 100 | connected_ms          | 50   | 134.9 | 161.9 | 173.3 | 174.2| 135.6 |
| 100 | ping_rtt_ms           | 640  | 1.9   | 4.1   | 4.6   | 5.0  | 2.0   |
| 100 | transcript_latency_ms | 2497 | 0.6   | 2.0   | 4.8   | 59.4 | 0.9   |
| 200 | connect_ms            | 100  | 36.0  | 74.8  | 75.5  | 75.9 | 47.7  |
| 200 | connected_ms          | 100  | 173.6 | 213.2 | 219.6 | 232.9| 171.8 |
| 200 | ping_rtt_ms           | 1210 | 2.5   | 18.6  | 19.6  | 58.2 | 4.0   |
| 200 | transcript_latency_ms | 4641 | 0.4   | 2.3   | 7.9   | 49.5 | 0.9   |

Backend resource usage (whole run, `ps` sampled every 1s, 80 samples):
CPU mean 13.6%, max 38.2% (one core); RSS mean 67.7MB, max 116.1MB.

**Where it degrades:** `connect_ms`/`connected_ms` (rows tagged by stage =
when that socket *opened*) grow with each stage — median time to
`{"status":"connected"}` goes from 48ms at 10 simultaneous new sockets to
174ms at 200. That's the cost of a thundering-herd burst of new handshakes
(all `to_add` sockets for a stage are opened in the same event-loop tick,
see `loadtest/README.md`'s caveats) landing on one asyncio event loop, not a
steady-state cost. `ping_rtt_ms` and `transcript_latency_ms` — sampled
continuously, tagged by whichever stage is current — stay under ~2.5ms at
p50 and single digits at p95 through all four stages; delivery of content
already in flight barely moves even as the connection count quadruples.
Nothing here points to a code bottleneck at these concurrency levels on this
machine.

## Scenario (b): fan-out — one streamer + M viewers per meeting

```bash
cd loadtest
../backend/.venv/bin/python -m wsload.run fanout \
  --meetings 15 --viewers 8 --fanout-hold 30 --server-pid 50688 --out results/fanout-run1.json
../backend/.venv/bin/python -m wsload.run fanout \
  --meetings 10 --viewers 20 --fanout-hold 30 --server-pid 50688 --out results/fanout-run2.json
```

| run | sockets | metric | n | p50 | p95 | p99 | max | mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15 meetings x 8 viewers  | 135 | connect_ms            | 135  | 2.0 | 4.7  | 6.7  | 7.3  | 2.3 |
| 15 meetings x 8 viewers  | 135 | connected_ms          | 135  | 3.7 | 11.3 | 13.4 | 13.6 | 4.3 |
| 15 meetings x 8 viewers  | 135 | ping_rtt_ms           | 1340 | 1.0 | 3.7  | 7.6  | 17.7 | 1.4 |
| 15 meetings x 8 viewers  | 135 | transcript_latency_ms | 5289 | 1.6 | 4.7  | 6.4  | 16.5 | 2.0 |
| 10 meetings x 20 viewers | 210 | connect_ms            | 210  | 1.8 | 5.8  | 16.1 | 34.4 | 2.6 |
| 10 meetings x 20 viewers | 210 | connected_ms          | 210  | 3.9 | 9.4  | 50.7 | 57.0 | 5.4 |
| 10 meetings x 20 viewers | 210 | ping_rtt_ms           | 2081 | 1.0 | 3.4  | 10.8 | 18.0 | 1.4 |
| 10 meetings x 20 viewers | 210 | transcript_latency_ms | 8065 | 2.6 | 6.5  | 12.0 | 51.8 | 3.1 |

Both runs: all connections opened, all closed `1000`, zero errors, zero
sequence gaps/duplicates (1304 and 1994 final segments received). Backend
CPU stayed under 21% of one core (mean 6.1-6.3%); RSS peaked at 124MB.

**Where it degrades:** doubling viewers-per-meeting (8 -> 20, at roughly half
the meeting count so total sockets are comparable, 135 vs 210) raises
transcript delivery latency modestly (p50 1.6ms -> 2.6ms, p95 4.7ms ->
6.5ms) — consistent with `MeetingSession._deliver` looping over more
subscriber queues per published message. It's a real, measurable, and small
cost, not a bottleneck at these fan-out sizes on this machine.

## Bug/finding fixed during this test

`POST /api/meetings` is rate-limited to 20/minute per client IP. Provisioning
the ~200 distinct meetings the ramp scenario needs — all from the load
generator's one IP — tripped it immediately (`429`s killed the first run).
The limiter itself isn't a bug (it's a legitimate anti-abuse control that
would never see this pattern from real, IP-diverse traffic); what was missing
was a way to raise it for a local run the way `WS_MAX_CONNECTIONS_PER_IP`
already can be. Fixed in `d0beda3`: `CREATE_MEETING_RATE_LIMIT` (default
`20/minute`, unchanged in production) makes the slowapi spec configurable,
with a test (`test_rate_limit_is_configurable`) covering it. Re-ran after the
fix; the numbers above are from that re-run.

## Not covered here

Deepgram mode (real audio, real upstream latency) and Groq-backed insight
generation under concurrent load are out of scope for this pass — both need
paid API keys and would add cost per run. The mock-mode numbers above
isolate the transport/fan-out path (WebSocket accept, the per-meeting
asyncio pump, Redis relay, per-subscriber queues) from transcription-provider
latency.
