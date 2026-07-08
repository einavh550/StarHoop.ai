# StarHoop.ai

**AI-powered basketball highlight platform for coaches.**

Upload a game video. The system automatically detects every player, reads their jersey numbers, tracks their movements, recognises on-court events, and generates personalised highlight reels — one per player, polished and ready to share.

---

## What it does

A coach uploads a raw game video from their Android phone. The backend:

1. Stores the video and creates a processing job
2. Sends it to a GPU worker (Modal serverless) running RF-DETR + SAM-2 + SigLIP + PaddleOCR
3. Detects players frame-by-frame, tracks them across the game, reads jersey numbers, and classifies team membership
4. Maps every tracked jersey to the coach's roster
5. Recognises highlight events: jump shots, layups, blocks, possessions, made/missed shots
6. Extracts per-player highlight clips and stitches them into a reel
7. Composes a polished reel with intro card, lower-thirds, music bed, and team branding
8. Serves the final reel to the Android app for playback and download

---

## Tech stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI (Python 3.12) |
| Database | PostgreSQL 16 + SQLAlchemy 2 + Alembic |
| GPU inference | Modal serverless (RF-DETR, SAM-2, SigLIP, PaddleOCR) |
| Object storage | Cloudflare R2 (S3-compatible) |
| Video processing | ffmpeg |
| Containerisation | Docker + Docker Compose |
| Auth | JWT (HS256, 30-day tokens) |
| Mobile frontend | Android (Kotlin + Jetpack Compose) — in active development |

---

## Project structure

```
StarHoop.ai/
├── src/app/
│   ├── main.py                  # FastAPI app factory + router registration
│   ├── api/routes/              # HTTP endpoints
│   │   ├── auth.py              # Register / login / profile
│   │   ├── videos.py            # Upload, status, list, cancel
│   │   ├── highlights.py        # Extract, compose, download
│   │   ├── teams.py             # Team + roster CRUD
│   │   ├── player_mapping.py    # Jersey → roster mapping
│   │   ├── actions.py           # Action recognition trigger
│   │   ├── exports.py           # Annotated full-video export
│   │   └── assets.py            # Music / branding / player photo upload
│   ├── cv/                      # Computer-vision & media pipeline
│   │   ├── mapping.py           # Jersey aggregation + roster matching
│   │   ├── actions.py           # Heuristic shot-attempt detection
│   │   ├── highlights/          # Event derivation, clip extraction, composition
│   │   ├── annotated_export.py  # Bounding-box overlay renderer
│   │   ├── r2_storage.py        # Cloudflare R2 upload/download
│   │   ├── orchestration.py     # Modal job spawning + chunked fan-out
│   │   └── schemas.py           # Pydantic request/response models
│   ├── db/
│   │   ├── models/              # SQLAlchemy ORM models
│   │   └── session.py           # Engine + session factory
│   └── core/
│       ├── config.py            # All settings (pydantic-settings)
│       ├── auth.py              # JWT utilities + FastAPI dependency
│       └── security.py          # HMAC webhook signing
├── alembic/versions/            # Database migration history
├── modal_app/                   # Modal GPU worker image + inference code
├── tests/                       # Unit and integration test suite
├── tools/                       # CLI helpers (colab export, ingest test)
├── docs/                        # Guides, specs, and reference documents
├── docker-compose.yml           # PostgreSQL + API services
├── Dockerfile                   # API image (Python 3.12-slim + ffmpeg)
├── requirements.txt             # Python dependencies (pinned)
├── .env.example                 # Environment variable template
└── pytest.ini                   # Test configuration
```

---

## Getting started

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- [ngrok](https://ngrok.com) — for the Modal webhook tunnel
- A [Modal](https://modal.com) account with the GPU worker deployed
- Cloudflare R2 bucket credentials

### 1. Configure environment

```bash
cp .env.example .env
# Fill in DATABASE_URL, R2 credentials, WEBHOOK_HMAC_SECRET, JWT_SECRET_KEY
```

### 2. Start the stack

```bash
docker compose up -d
```

### 3. Run database migrations

```bash
docker compose exec api alembic upgrade head
```

### 4. Open the ngrok tunnel

```bash
ngrok http 8000
# Copy the HTTPS URL into .env as WEBHOOK_BASE_URL
```

### 5. Verify

```bash
curl http://localhost:8000/health
# → {"status":"ok","database":"connected"}
```

Interactive API docs: **http://localhost:8000/docs**

See [`docs/STARTUP_GUIDE.md`](docs/STARTUP_GUIDE.md) for the full step-by-step startup sequence and troubleshooting.

---

## API overview

The full contract is documented live at `/docs` (Swagger UI) and `/openapi.json`. Key endpoint groups:

| Group | Base path | Auth required |
|-------|-----------|---------------|
| Auth | `/api/auth/` | Register/login open; `/me` requires token |
| Teams & roster | `/api/teams/` | Reads open; writes require Bearer token |
| Video jobs | `/api/videos/` | All open |
| Highlights | `/api/videos/{job_id}/highlights/` | All open |
| Player mapping | `/api/videos/{job_id}/player_mapping/` | Open |
| Assets | `/api/assets/` | Open |
| Health | `/health/` | Open |

Authentication uses **Bearer JWT** (`Authorization: Bearer <token>`). Tokens are valid for 30 days; re-login when expired (no refresh endpoint).

See [`docs/BACKEND_API_CONTRACT.txt`](docs/BACKEND_API_CONTRACT.txt) for the complete request/response contract with examples.

---

## Configuration

All settings live in `src/app/core/config.py` and are loaded from the `.env` file. Copy `.env.example` and fill in your values — never commit `.env`.

Key settings:

| Variable | Purpose |
|----------|---------|
| `DATABASE_URL` | PostgreSQL connection string |
| `JWT_SECRET_KEY` | Signs auth tokens — use a long random string in production |
| `ENABLE_MODAL_ORCHESTRATION` | Set `true` to send jobs to Modal GPU workers |
| `WEBHOOK_BASE_URL` | Public URL Modal uses to POST results back (your ngrok URL) |
| `WEBHOOK_HMAC_SECRET` | Shared secret between API and Modal worker |
| `R2_*` | Cloudflare R2 bucket credentials |

CV pipeline behaviour is controlled by feature flags (all default `true` in `.env`): `DEDUP_BY_PLAYER`, `TRACK_CONSOLIDATION`, `ACTION_TEMPORAL_VOTING`, `OPPONENT_TEAM_GATE`, `OVERLAP_RESOLUTION`, `PERIODIC_REDETECT_INTERVAL`.

---

## Development

```bash
# Run tests (requires a running PostgreSQL)
docker compose exec api pytest

# Check API logs
docker compose logs -f api

# Apply a new migration
docker compose exec api alembic upgrade head

# Rebuild the image after dependency changes
docker compose up -d --build api
```

---

## Docs

Additional documentation lives in [`docs/`](docs/):

| File | Contents |
|------|----------|
| [`STARTUP_GUIDE.md`](docs/STARTUP_GUIDE.md) | Full startup sequence and troubleshooting |
| [`BACKEND_API_CONTRACT.txt`](docs/BACKEND_API_CONTRACT.txt) | Complete API contract for Android integration |
| [`SCHEMA_DIAGRAM.md`](docs/SCHEMA_DIAGRAM.md) | Database entity-relationship diagram |
| [`TECH_SPEC.md`](docs/TECH_SPEC.md) | Technical specification |
| [`PROJECT_STRUCTURE.md`](docs/PROJECT_STRUCTURE.md) | Detailed project layout |
| [`QUICK_REFERENCE.md`](docs/QUICK_REFERENCE.md) | Common commands cheat sheet |
| [`android_app_instructions.md`](docs/android_app_instructions.md) | Android integration guide |
| [`cv_phase2_finetuning.md`](docs/cv_phase2_finetuning.md) | CV model fine-tuning roadmap |

---

## License

Proprietary — all rights reserved.
