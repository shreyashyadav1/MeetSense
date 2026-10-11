# Load testing the live-stream WebSocket

Exercises `backend/app/api/websocket.py` (`/ws/meetings/{id}/stream`) against a
locally running backend in mock-transcription mode. See `RESULTS.md` for the
numbers from actual runs on this machine.

## Tool choice: Python asyncio, not k6

The brief called for k6 (official `grafana/k6` Docker image) unless it can't
send binary frames the way the backend needs. It can: `k6/ws` has
`socket.sendBinary()` and the newer `k6/experimental/websockets` sends an
`ArrayBuffer` via `socket.send()`. So this isn't a capability gap — it's a fit
question, and a small asyncio script fit better here for three reasons:

1. **No new dependency or container.** `websockets==17.1` is already pinned in
   `backend/requirements.txt` (the backend's own tests use it for live-server
   checks), so `backend/.venv` runs the load generator with nothing extra
   installed. Running k6 would mean pulling and running another Docker
   container on an 8 GB machine that's already running Postgres, Redis, and
   other agents' containers alongside it — a real cost on this box, for a tool
   whose only job here is to open WebSockets and check JSON.
2. **The fan-out topology is easier as plain code.** Scenario (b) needs
   exactly one streamer plus M viewers *per meeting*, across many meetings at
   once. In k6 that means coordinating VUs/scenarios and sharing meeting IDs
   between them (`SharedArray`, `setup()`, `exec` per role). In asyncio it's
   `asyncio.gather` over a list of tasks, one per socket, each closing over
   the meeting ID it belongs to.
3. **Per-connection bookkeeping is the whole point.** Sequence-gap/duplicate
   detection, matching `ping`/`pong` round trips, and computing one-way
   transcript delivery latency all need small stateful per-socket logic
   that's simpler to write and debug directly in Python than in k6's JS
   sandbox with custom metrics.

The trade-off: k6 would give load distributed by a battle-tested engine with
its own reporting. This script is bespoke and only as correct as its tests
(see "Validating the tool" below) — but for one machine, one protocol, and a
handful of scenarios, that trade was worth it.

## One protocol addition: `emitted_at`

`TranscriptMessage` (`backend/app/models/ws.py`) gained one field,
`emitted_at: float` (server wall-clock seconds, `time.time()` at construction).
It's additive with a default factory — every existing call site is unchanged,
and a client that doesn't read the field is unaffected. This was added
because without it, "delivery latency" can only be inferred from `ping`/`pong`
round-trip time, which conflates send and receive delay and says nothing
about the message that actually matters (a transcript line). Since the load
generator and the backend run on the same machine, `client_recv_time -
emitted_at` is a real one-way latency with no clock-skew concerns — a rare
case where that comparison is trustworthy.

## Setup

```bash
# From the repo root. Ports chosen to avoid clashing with other local services.
docker run -d --rm --name mse-postgres -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=meetsense_test -p 5434:5432 postgres:16
docker run -d --rm --name mse-redis -p 6381:6379 redis:7

cd backend
python3.11 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
DATABASE_URL="postgresql://postgres:postgres@localhost:5434/meetsense_test" .venv/bin/alembic upgrade head

# Start the backend in mock mode, pointed at those containers, with two
# per-IP defensive limits raised — the load generator runs from one machine
# (one IP), so the production defaults would reject almost everything above
# a handful of concurrent sockets or meetings created per minute. Both are
# *local load-test-only* overrides: production keeps the tighter defaults.
MOCK_TRANSCRIPTION=true \
DATABASE_URL="postgresql://postgres:postgres@localhost:5434/meetsense_test" \
REDIS_URL="redis://localhost:6381" \
ALLOW_MEMORY_FALLBACK=false \
WS_MAX_CONNECTIONS_PER_IP=500 \
CREATE_MEETING_RATE_LIMIT=1000/minute \
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning &
echo "backend pid: $!"   # pass this to --server-pid below for CPU/RSS sampling
```

`CREATE_MEETING_RATE_LIMIT` didn't exist until this load test hit it: ramping
to 200 meetings from a single IP tripped the default 20/minute limit on
`POST /api/meetings` (working as designed — it's just not designed for one
host provisioning 200 meetings at once). See `RESULTS.md` for that finding.

## Running the scenarios

From `loadtest/` (so the `wsload` package and the default `results/` output
directory resolve correctly). The Setup block above leaves your shell in
`backend/`, so go to `loadtest/` via the repo root:

```bash
cd "$(git rev-parse --show-toplevel)/loadtest"

# (a) N concurrent meetings, one streaming socket each, ramping 10 -> 50 -> 100 -> 200
../backend/.venv/bin/python -m wsload.run ramp \
  --stages 10,50,100,200 --stage-hold 20 --server-pid <PID>

# (b) fan-out: one streamer + M viewers per meeting, several meetings at once
../backend/.venv/bin/python -m wsload.run fanout \
  --meetings 15 --viewers 8 --fanout-hold 30 --server-pid <PID>
```

Each run prints a summary table and writes the full raw report as JSON to
`results/<scenario>-<unix time>.json` (gitignored — regenerate instead of
committing). `RESULTS.md` is the committed, human-written summary.

## What's measured

Every simulated socket sends `{"type": "ping"}` every 3s and a graceful
`{"type": "stop"}` at the end of its run; a "streamer" socket also sends a
1000-byte filler frame every 250ms (mock mode never inspects audio bytes, so
this exercises the same receive-loop path real audio would without needing a
real encoder).

| Metric | How |
| --- | --- |
| `connect_ms` | time from opening the socket to the WebSocket handshake completing |
| `connected_ms` | handshake done -> `{"status":"connected"}` received |
| `ping_rtt_ms` | `ping` sent -> matching `pong` received |
| `transcript_latency_ms` | `client_recv_time - emitted_at` for every `transcript` message (final and interim) |
| sequence gaps / duplicates | per-socket: consecutive final `sequence` numbers should increase by exactly 1 |
| close / error codes | the WebSocket close code and any `{"type":"error"}` payload, per socket |
| backend CPU / RSS | `ps -o %cpu=,rss=` on the backend PID, sampled every 1s for the run's duration |

Samples are tagged with whichever stage is current *when recorded*, not when
the socket was opened, since a ramp's early sockets stay open into later,
busier stages.

### A mock-mode nuance for scenario (b)

`MeetingSession` runs at most one transcription source per meeting, and in
mock mode every connecting socket attempts to start it — the first one
scheduled by the server wins ownership, and since mock transcription ignores
audio content entirely, ownership doesn't change what any socket receives.
So "streamer" here is nominal in mock mode: it still sends the audio frames
scenario (b) asks for, but the fan-out path being measured (one
`MeetingSession` publishing to N subscriber queues) is exercised identically
by all N+1 sockets. That's the mechanism this scenario exists to test.

## Validating the tool

Before the timed runs recorded in `RESULTS.md`, the generator was smoke-tested
against small numbers of connections and, separately, against a throwaway
server started with a low `WS_MAX_CONNECTIONS_PER_IP` to confirm the
error/close-code path is captured correctly (it recorded `too_many_connections`
errors with the matching `1013` close codes, alongside clean `1000` closes for
the connections that were accepted). Both raw JSON reports are reproducible by
rerunning the commands above; they aren't committed as they're throwaway.

## Caveats

- One 8 GB MacBook Air running the backend, both containers, *and* the load
  generator at once. Numbers describe this machine's mock-mode ceiling, not
  the backend's ceiling on real hardware with real Deepgram audio.
- Anything else on the machine competes for the same cores and RAM, including
  other Docker containers (they all share one VM). Check that the machine is
  quiet right before a timed run, and record what you saw next to the numbers:

  ```bash
  top -l 3 -s 2 -n 0 | grep "CPU usage"   # idle should sit well above ~60%
  sysctl vm.swapusage                     # heavy swap use means paging can masquerade as latency
  docker stats --no-stream                # who else is busy inside the Docker VM
  ```
- Client and server share a CPU. At the higher concurrency stages the load
  generator's own event loop is doing real work (JSON parsing, ~one wakeup
  per socket per 250ms); a slower client tick can widen p95s in a way that
  isn't purely server-side. `connect_ms`/`connected_ms` are the closest
  approximations to server-only latency, since they don't depend on the
  client already juggling many open sockets.
- Mock transcription generates a fixed 20-line script per meeting on its own
  schedule; it isn't shaped by the audio frames sent, so this measures
  transport and fan-out cost, not transcription cost.
