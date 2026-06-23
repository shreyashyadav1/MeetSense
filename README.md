# MeetSense AI

A full-stack AI-powered meeting assistant that captures live speech, transcribes it in real time, and generates structured meeting insights using large language models.

Built as a portfolio project demonstrating production-grade full-stack engineering across real-time WebSockets, streaming speech-to-text, async Python, LLM-driven structured output, and containerized deployment.

**Live demo:** https://meet-sense.vercel.app

---

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [Pages](#pages)
- [API Reference](#api-reference)
- [Database Schema](#database-schema)
- [Environment Variables](#environment-variables)
- [Local Development Setup](#local-development-setup)
- [Docker Setup](#docker-setup)
- [Project Phases](#project-phases)
- [Screenshots](#screenshots)
- [License](#license)

---

## Features

- Live microphone capture with real-time speech-to-text transcription
- Speaker identification — Speaker 1, 2, 3, 4 labeled per segment
- Interim results (ghost text while speaking) + finalized transcript segments
- AI-generated meeting insights:
  - Executive summary
  - Action items
  - Key decisions
  - Questions raised
  - Follow-up email draft (one-click copy)
- Persistent meeting history stored in PostgreSQL
- Searchable meeting list on the dashboard
- Rate-limited AI summarization endpoint (5 requests/min)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18, TypeScript, Vite, React Router v6, Axios |
| Styling | CSS custom properties, light theme |
| Backend | Python 3.11, FastAPI, uvicorn (hot-reload) |
| Real-time | WebSockets — browser to FastAPI to Deepgram |
| Speech-to-Text | Deepgram nova-2, streaming WebSocket, WebM/Opus via MediaRecorder API |
| AI / LLM | Groq API, llama-3.3-70b-versatile, structured JSON output |
| Database | PostgreSQL via Supabase, SQLAlchemy 2.0 async, asyncpg driver |
| Pub/Sub | Redis 7, redis-py asyncio |
| Containerization | Docker, Docker Compose (backend, frontend/nginx, redis) |
| Rate Limiting | slowapi |

---

## Architecture

```
Browser (React + TypeScript)
  │ MediaRecorder audio (WebM/Opus, 250ms chunks)
  │ WebSocket binary frames
  ▼
FastAPI WebSocket Server
  │ binary audio chunks
  ▼
Deepgram nova-2 (streaming STT)
  │ transcript events (interim + final)
  ▼
Redis Pub/Sub  ──────────────────────► WebSocket → Browser (live transcript)
  │
  ▼ (on meeting end)
Groq llama-3.3-70b
  │ structured JSON insights
  ▼
PostgreSQL (Supabase)
  meetings | transcript_segments | meeting_insights
```

The browser opens a single WebSocket to FastAPI. FastAPI proxies raw audio chunks upstream to Deepgram's streaming STT API. Deepgram returns interim and final transcript events, which FastAPI publishes to a Redis channel. A separate consumer reads from Redis and pushes transcript messages back down the WebSocket to the browser. On meeting end, the full transcript is sent to Groq for structured insight generation, and the result is persisted to PostgreSQL.

---

## Pages

| Route | Page | Description |
|---|---|---|
| `/` | Dashboard | Meeting history, search, create new meeting |
| `/meeting/:id/live` | Meeting Room | Live transcript, mic controls, audio level meter |
| `/meeting/:id` | Meeting Details | Full transcript + AI insights panel |

---

## API Reference

```
POST   /api/meetings                    Create a new meeting
GET    /api/meetings                    List all meetings
GET    /api/meetings/{id}               Get a single meeting
POST   /api/meetings/{id}/end           End a meeting
GET    /api/meetings/{id}/transcript    Get transcript segments
POST   /api/meetings/{id}/summarize     Generate AI insights  (rate limit: 5/min)
GET    /api/meetings/{id}/insights      Fetch saved insights
WS     /ws/meetings/{id}/stream         Live audio + transcript stream
```

---

## Database Schema

```sql
meetings (
  id           UUID PRIMARY KEY,
  title        TEXT,
  status       TEXT,        -- 'active' | 'ended'
  started_at   TIMESTAMPTZ,
  ended_at     TIMESTAMPTZ
)

transcript_segments (
  id           UUID PRIMARY KEY,
  meeting_id   UUID REFERENCES meetings(id),
  speaker      TEXT,        -- 'Speaker 1' .. 'Speaker 4'
  text         TEXT,
  timestamp    FLOAT,
  confidence   FLOAT,
  is_final     BOOLEAN
)

meeting_insights (
  id               UUID PRIMARY KEY,
  meeting_id       UUID REFERENCES meetings(id),
  summary          TEXT,
  action_items     TEXT[],
  decisions        TEXT[],
  questions_raised TEXT[],
  follow_up_email  TEXT,
  generated_at     TIMESTAMPTZ
)
```

---

## Environment Variables

Create `backend/.env` from `backend/.env.example` and populate the following keys:

```env
# backend/.env

DEEPGRAM_API_KEY=     # console.deepgram.com — free tier available
GROQ_API_KEY=         # console.groq.com — free tier available
DATABASE_URL=         # postgresql+asyncpg://postgres:password@host:5432/postgres
REDIS_URL=            # redis://localhost:6379
```

**Getting API keys:**
- Deepgram: [console.deepgram.com](https://console.deepgram.com) — free tier includes 200 hours/month
- Groq: [console.groq.com](https://console.groq.com) — free tier with generous rate limits
- Supabase: [supabase.com](https://supabase.com) — free tier includes a hosted PostgreSQL instance

---

## Local Development Setup

### Prerequisites

- Python 3.11+
- Node.js 18+
- Redis running locally (`redis-server` or via Docker)
- A Supabase project (or any PostgreSQL instance)

### Backend

```bash
git clone https://github.com/shreyashyadav1/MeetSense.git
cd MeetSense/backend

python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env            # fill in API keys and DATABASE_URL
python main.py                  # starts on http://localhost:8000
```

The backend runs with uvicorn in hot-reload mode. The WebSocket endpoint is available at `ws://localhost:8000/ws/meetings/{id}/stream`.

### Frontend

Open a second terminal:

```bash
cd MeetSense/frontend
npm install
npm run dev                     # starts on http://localhost:5173
```

Vite proxies API and WebSocket requests to `localhost:8000` automatically during development.

---

## Docker Setup

Docker Compose brings up three services: FastAPI backend, React frontend served via nginx, and Redis.

```bash
# From the project root
cp backend/.env.example backend/.env   # fill in API keys and DATABASE_URL

docker compose up --build
```

| Service | URL |
|---|---|
| Frontend (nginx) | http://localhost |
| Backend (FastAPI) | http://localhost:8000 |
| Redis | localhost:6379 (internal) |

To tear down:

```bash
docker compose down
```

---

## Project Phases

- Phase 1: React + FastAPI + WebSocket foundation
- Phase 2: Microphone capture + Deepgram real-time STT
- Phase 3: Groq AI insights (summary, action items, decisions, follow-up email)
- Phase 4: PostgreSQL persistence via Supabase
- Phase 5: Redis pub/sub, Docker Compose, rate limiting

---

## Screenshots

### Dashboard
![Dashboard](docs/screenshots/dashboard.png)

### Meeting Room (Active)
![Meeting Room](docs/screenshots/meeting-room.png)

### Meeting Detail with AI Insights Panel
![Meeting Detail](docs/screenshots/meeting-detail.png)

### Mobile View
![Mobile](docs/screenshots/mobile.png)

---

## License

MIT
