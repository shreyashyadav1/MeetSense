# Load test results

**Date:** 2026-10-10, US Eastern (the runs took place between 00:47 and 00:51 UTC on 2026-10-11).
**Commit:** `a6df65f` (`fix(evals): send reasoning_effort the way production does`) on
`feat/load-test-evals`, rebased onto master `78bfede`, clean working tree. The backend's load
path (WebSocket endpoint, mock source, Redis relay, rate limiter) is master plus two commits,
`feat(ws): add a server emit timestamp to transcript messages` and `feat(api): make the
create-meeting rate limit configurable`; the commits after those touch only docs and the evals.
If a rebase or squash changes the hash, look the commit up by its subject.
**Machine:** MacBook Air, Apple M3 (8 cores), 8 GB RAM, macOS 26.5.2. Backend run natively
(not in Docker) in `backend/.venv` (Python 3.11.15); PostgreSQL 16.15 and Redis 7.4.11 in
Docker (`postgres:16`, `redis:7`), on non-default ports to avoid other local services.
**Mode:** `MOCK_TRANSCRIPTION=true` (scripted transcript, no Deepgram calls).
**Load generator:** `loadtest/wsload`, run from the `loadtest/` directory, on the same machine
as the backend — see the caveats in `loadtest/README.md` before comparing these numbers to
anything else.

## Conditions during these runs

This is a shared 8 GB laptop, and the numbers below were taken on it as it was, not on a
quiet machine:

- Before each run 6.1-6.6 GiB of swap was in use (of a 7-8 GiB total) and at most about
  200 MB of RAM was unused, and the machine kept paging while the runs were going (table
  below). Other workloads came and went, including containers in the same Docker VM; a batch
  job there had pegged all 8 cores for several minutes shortly before these runs.
- So each scenario was gated on the machine and judged on the machine, never on its results
  (the rule was fixed before the first run): it started only after whole-machine CPU had been
  at least 60% idle for 25 seconds, and would have been discarded and repeated if mean idle
  CPU during the run came in under 40%. All three runs passed on the first attempt; none was
  discarded.

| run | machine CPU idle, mean (min) | swapped in / out during the run | RAM unused at end |
| --- | --- | --- | --- |
| ramp | 65.6% (44.8%) | 2.26 / 2.32 GiB | 98 MB |
| fan-out, 15 meetings x 8 viewers | 59.9% (38.6%) | 1.08 / 1.12 GiB | 88 MB |
| fan-out, 10 meetings x 20 viewers | 73.7% (54.3%) | 0.52 / 0.00 GiB | 135 MB |

Measured with `top -l N -s 3 -n 0` (whole-machine CPU every 3 s, first sample dropped) and
`vm_stat` / `sysctl vm.swapusage` before and after each run. Paging adds latency to anything
that touches a swapped-out page and shrinks a process's resident size, so read the
connection-setup times and latency tails below as possibly including stalls that belong to
the machine, and the RSS figures as a floor.

## Setup used for every run below

Exactly the README's Setup block, run from the repo root against fresh containers
(the only deviation: the backend's log went to a file, since the tool driving the
run can't have a background process holding its terminal):

```bash
docker run -d --rm --name mse-postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=meetsense_test -p 5434:5432 postgres:16
docker run -d --rm --name mse-redis -p 6381:6379 redis:7

cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
DATABASE_URL="postgresql://postgres:postgres@localhost:5434/meetsense_test" .venv/bin/alembic upgrade head

MOCK_TRANSCRIPTION=true \
DATABASE_URL="postgresql://postgres:postgres@localhost:5434/meetsense_test" \
REDIS_URL="redis://localhost:6381" \
ALLOW_MEMORY_FALLBACK=false \
WS_MAX_CONNECTIONS_PER_IP=500 \
CREATE_MEETING_RATE_LIMIT=1000/minute \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning &
echo "backend pid: $!"   # 65113 for these runs
```

The same backend process served all three runs below, in this order, so the ramp ran
against a freshly started server.

## Scenario (a): ramp — 10 -> 50 -> 100 -> 200 concurrent meetings

```bash
cd "$(git rev-parse --show-toplevel)/loadtest"
../backend/.venv/bin/python -m wsload.run ramp \
  --stages 10,50,100,200 --stage-hold 20 --server-pid 65113
```

One streaming socket per meeting, each sending a 1000-byte frame every 250ms. Ran
00:47:13 -> 00:48:34 UTC (81.4s). All 200 connections opened; all closed `1000` (clean);
zero `error` frames; **2,071 final transcript segments received, 0 sequence gaps, 0
duplicates**, across every stage. Raw report: `results/ramp-1791679714.json` (gitignored).

| stage | metric | n | p50 | p95 | p99 | max | mean |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | connect_ms | 10 | 14.0 | 15.0 | 15.2 | 15.2 | 14.0 |
| 10 | connected_ms | 10 | 68.0 | 71.4 | 71.4 | 71.4 | 67.8 |
| 10 | ping_rtt_ms | 60 | 0.8 | 3.0 | 3.3 | 3.5 | 1.3 |
| 10 | transcript_latency_ms | 250 | 0.8 | 1.9 | 5.0 | 25.4 | 1.1 |
| 50 | connect_ms | 40 | 18.2 | 22.3 | 22.7 | 22.9 | 18.3 |
| 50 | connected_ms | 40 | 134.0 | 154.4 | 158.9 | 159.6 | 134.3 |
| 50 | ping_rtt_ms | 310 | 2.4 | 4.9 | 5.7 | 6.1 | 2.5 |
| 50 | transcript_latency_ms | 1248 | 0.5 | 2.7 | 8.7 | 44.5 | 1.0 |
| 100 | connect_ms | 50 | 19.8 | 23.4 | 23.8 | 24.0 | 20.1 |
| 100 | connected_ms | 50 | 136.7 | 185.8 | 189.6 | 190.1 | 141.9 |
| 100 | ping_rtt_ms | 650 | 1.8 | 11.5 | 30.4 | 30.6 | 3.2 |
| 100 | transcript_latency_ms | 2507 | 0.4 | 2.4 | 26.6 | 78.7 | 1.3 |
| 200 | connect_ms | 100 | 136.0 | 165.2 | 166.7 | 167.1 | 138.3 |
| 200 | connected_ms | 100 | 163.9 | 221.0 | 231.6 | 231.8 | 167.5 |
| 200 | ping_rtt_ms | 1200 | 3.3 | 8.9 | 9.7 | 19.2 | 3.9 |
| 200 | transcript_latency_ms | 4556 | 0.4 | 2.2 | 16.6 | 50.5 | 1.0 |

Backend resource usage (whole run, `ps` sampled every 1s, 81 samples): CPU mean 10.8%, max
74.5% (of one core); RSS mean 46.3MB, max 109.7MB.

**What stays flat, what degrades:**

- *Delivery stays flat.* `transcript_latency_ms` (server emit to client receive) has p50
  0.4-0.8ms and p95 1.9-2.7ms at every stage, from 10 to 200 concurrent meetings, and
  `ping_rtt_ms` p50 stays at 0.8-3.3ms.
- *Getting connected degrades with the size of the burst.* All of a stage's new sockets are
  opened in the same event-loop tick, so this describes N simultaneous joins, not a trickle.
  `connected_ms` (handshake done to the `connected` frame) is p50 68ms for the first 10
  sockets, then 134, 137 and 164ms for the bursts of 40, 50 and 100 that followed (p95 71,
  154, 186, 221ms). `connect_ms` (the WebSocket handshake alone) is p50 14, 18 and 20ms
  through the first three stages, then 136ms (p95 165ms) for the 100 sockets opened at stage
  200 — the one step in the table that looks like a wall rather than a slope.
- *Tails widen from 100 meetings up.* Ping RTT p99 reaches 30.4ms at stage 100 (3.3ms at
  stage 10) and transcript latency p99 26.6ms with a 78.7ms max (5.0ms p99 at stage 10),
  while transcript p95 stays at 2-3ms.
- *Not profiled.* Before it sends `connected`, each new socket looks its meeting up in
  Postgres through SQLAlchemy's default pool (5 connections plus 10 overflow, pre-pinged on
  checkout; `backend/app/db/base.py`), so a burst of 50-100 joins queues behind at most 15
  connections. That is a candidate worth profiling, not a finding. The machine was also
  swapping during this run (see above), which alone can put 100ms-scale stalls on a handful of
  operations. Nothing here shows errors or lost messages at this scale; what it does show is
  setup time growing with burst size and wider tails past 100 meetings.

## Scenario (b): fan-out — one streamer + M viewers per meeting

```bash
cd "$(git rev-parse --show-toplevel)/loadtest"
../backend/.venv/bin/python -m wsload.run fanout \
  --meetings 15 --viewers 8 --fanout-hold 30 --server-pid 65113
../backend/.venv/bin/python -m wsload.run fanout \
  --meetings 10 --viewers 20 --fanout-hold 30 --server-pid 65113
```

Ran 00:48:59 -> 00:49:32 UTC and 00:50:30 -> 00:51:03 UTC (33.0s each). Raw reports:
`results/fanout-1791679772.json` and `results/fanout-1791679863.json` (gitignored).

| run | sockets | metric | n | p50 | p95 | p99 | max | mean |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 15 meetings x 8 viewers | 135 | connect_ms | 135 | 1.5 | 3.9 | 17.1 | 48.8 | 2.3 |
| 15 meetings x 8 viewers | 135 | connected_ms | 135 | 2.1 | 9.0 | 66.7 | 99.0 | 4.4 |
| 15 meetings x 8 viewers | 135 | ping_rtt_ms | 1311 | 0.8 | 3.2 | 8.3 | 16.3 | 1.2 |
| 15 meetings x 8 viewers | 135 | transcript_latency_ms | 5106 | 1.2 | 3.2 | 7.5 | 26.7 | 1.5 |
| 10 meetings x 20 viewers | 210 | connect_ms | 210 | 2.0 | 171.4 | 225.2 | 228.8 | 20.9 |
| 10 meetings x 20 viewers | 210 | connected_ms | 210 | 4.0 | 144.2 | 255.1 | 257.5 | 26.2 |
| 10 meetings x 20 viewers | 210 | ping_rtt_ms | 2084 | 0.9 | 3.8 | 9.4 | 43.1 | 1.4 |
| 10 meetings x 20 viewers | 210 | transcript_latency_ms | 8196 | 2.8 | 5.9 | 17.3 | 28.6 | 3.1 |

Both runs: every connection opened and closed `1000`, zero errors, zero sequence
gaps/duplicates (1,254 and 2,034 final segments received). Backend CPU mean 5.5% and 6.8%,
max 13.2% and 29.9% (of one core); RSS max 58.6MB and 118.4MB.

**What stays flat, what degrades:**

- *Delivery cost grows with viewers per meeting.* From 8 to 20 viewers (135 to 210 sockets,
  at fewer meetings), transcript latency goes from p50 1.2ms to 2.8ms, p95 3.2ms to 5.9ms and
  p99 7.5ms to 17.3ms; ping RTT p95 goes from 3.2ms to 3.8ms. That is consistent with
  `MeetingSession._deliver` walking more subscriber queues for every published message — real,
  measurable, and small at these sizes.
- *A connection-setup tail in the 10 x 20 run.* The median socket completed its handshake in
  2.0ms (4.0ms to `connected`), but about 10 of the 210 took 170-230ms to connect (p95 171ms,
  max 229ms) and 144-258ms to receive `connected` (p95 144ms, max 258ms); in the 15 x 8 run
  the slowest sockets took 49ms and 99ms. The medians barely moved, which suggests a short
  stall hitting whatever was connecting at that moment (the machine was swapping, above)
  rather than a per-socket cost, but I did not isolate it.

## Finding fixed while first running these scenarios

`POST /api/meetings` is rate-limited to 20/minute per client IP. Provisioning
the ~200 distinct meetings the ramp scenario needs — all from the load
generator's one IP — tripped it immediately (`429`s killed the first attempt).
The limiter itself isn't a bug (it's a legitimate anti-abuse control that
would never see this pattern from real, IP-diverse traffic); what was missing
was a way to raise it for a local run the way `WS_MAX_CONNECTIONS_PER_IP`
already can be. Fixed by `feat(api): make the create-meeting rate limit configurable`:
`CREATE_MEETING_RATE_LIMIT` (default `20/minute`, unchanged in production) makes the
slowapi spec configurable, with a test (`test_rate_limit_is_configurable`) covering it.
Both overrides in the setup block above are local load-test settings only.

## Not covered here

Deepgram mode (real audio, real upstream latency) and Groq-backed insight
generation under concurrent load are out of scope for this pass — both need
paid API keys and would add cost per run. The mock-mode numbers above
isolate the transport/fan-out path (WebSocket accept, the per-meeting
asyncio pump, Redis relay, per-subscriber queues) from transcription-provider
latency.
