# StarHoop.ai 🏀 — AI-Powered Basketball Analytics for Youth Coaches

**Status:** Milestones 1–5 complete and tested. Milestone 6 is the next implementation target.

---

## Overview

**StarHoop.ai** is an AI-powered platform that automates basketball game analysis. Coaches upload a raw game video -> the system automatically detects, tracks, and identifies players by jersey number and team -> coaches receive structured, queryable game intelligence plus generated highlight media.

**Tech Stack:**
- **Backend:** FastAPI (Python) + PostgreSQL + SQLAlchemy ORM
- **GPU Inference:** Modal serverless (RF-DETR, SAM-2, SigLIP, SmolVLM2)
- **Storage:** Cloudflare R2 (S3-compatible)
- **Containerization:** Docker + Docker Compose
- **Video Processing:** ffmpeg
- **Mobile Frontend:** Android (Kotlin) — planned

---

## Project Structure

```
StarHoop.ai/
├── src/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── db/models/           # SQLAlchemy ORM models (VideoJob, DetectionFrame, etc.)
│   │   ├── api/routes/          # API endpoints
│   │   ├── cv/                  # Computer vision + media pipeline
│   │   │   ├── actions.py       # Action recognition
│   │   │   ├── annotated_export.py  # Annotated full-video rendering
│   │   │   ├── highlights/      # M5 clip extraction/stitching modules
│   │   │   └── mapping.py       # Jersey -> player mapping
│   │   └── core/                # Config/security/runtime helpers
├── alembic/versions/            # DB schema versions
├── modal_app/                   # Modal GPU app image + workers
├── docker-compose.yml           # PostgreSQL + API services
├── Dockerfile                   # API image (includes ffmpeg)
├── STARTUP_GUIDE.md             # Boot sequence and ops commands
└── README.md                    # This file
```

---

## Milestones Implemented & Tested (1–5)

### ✅ Milestone 1: Object Detection (RF-DETR)
- Detects players, ball, rim, jersey numbers, and key action classes.
- Runs on Modal GPU.
- **Output:** Per-frame detections with class names, confidences, boxes, and trackable entities.

### ✅ Milestone 2: Real-Time Tracking (SAM-2)
- Propagates masks and stable track IDs across frames.
- Initialized from detector observations, then tracked through video.
- **Output:** Persistent per-track identity and segmentation continuity.

### ✅ Milestone 3: Team Classification (SigLIP + clustering)
- Embeds player crops with SigLIP and assigns team clusters.
- **Output:** Team assignment per track with consistent side labeling.

### ✅ Milestone 4: Jersey OCR & Identity Mapping
- Reads jersey numbers with SmolVLM2 and maps to roster players.
- Includes aggregation and confidence gating for stability.
- Added **annotated full-video export** with smooth interpolation and centered labels.

### ✅ Milestone 5: Highlight Clip Extraction & Stitching
**Goal achieved:** Auto-generate coach-ready highlight reels from derived game events.

**Implemented scope:**
- Event derivation from action detections + frame-level classes.
- Clip extraction and reel stitching via ffmpeg.
- Persistence layer for reels and clips:
	- `highlight_reels`
	- `highlight_clips`
- Hybrid output model:
	- Master reel (all events, all players)
	- Optional minimal per-player reel (same pipeline, filtered by player)
- Source modes for extraction:
	- `source=clean` (raw source video)
	- `source=annotated` (overlay source)
- **Single-player annotation behavior (implemented):**
	- For per-player reels with `source=annotated`, only the selected player is boxed/labeled.
	- All other players remain unannotated.

**Primary entry point:** `POST /api/videos/{job_id}/highlights/extract`

---

## Milestone 6 (Next): Professional Personalized Reel Composition

**Goal:** Turn M5 raw per-player reels into polished, share-ready highlight products.

**Planned implementation scope:**
- Intro/title card with player identity and game metadata.
- Rich overlays (player name/number, event chips, optional stats bar).
- Visual composition polish (timed transitions and pacing).
- Music bed integration (with safe level control/ducking).
- Branding/watermark package and export profiles.

**Design boundary:**
- Filtering and event selection remain in M5.
- M6 focuses on presentation/composition quality on top of M5 outputs.

---

## API Endpoints (Live)

| Method | Endpoint | Purpose | Status |
|--------|----------|---------|--------|
| `POST` | `/api/videos/upload` | Create job and upload video | ✅ Live |
| `GET` | `/api/videos/{job_id}` | Poll job status/progress | ✅ Live |
| `GET` | `/api/videos/{job_id}/results` | Retrieve structured detections | ✅ Live |
| `POST` | `/api/videos/{job_id}/exports/annotated` | Generate annotated full MP4 | ✅ Live |
| `GET` | `/api/videos/{job_id}/exports/annotated/{export_id}` | Annotated export status | ✅ Live |
| `GET` | `/api/videos/{job_id}/exports/annotated/{export_id}/download` | Download annotated MP4 | ✅ Live |
| `POST` | `/api/videos/{job_id}/actions/auto` | Run action recognizer | ✅ Live |
| `POST` | `/api/videos/{job_id}/highlights/extract` | Create M5 highlight reel | ✅ Live |
| `GET` | `/api/videos/{job_id}/highlights/{reel_id}` | Reel metadata/status | ✅ Live |
| `GET` | `/api/videos/{job_id}/highlights/{reel_id}/download` | Download stitched reel | ✅ Live |
| `GET` | `/api/videos/{job_id}/highlights/{reel_id}/clips/{clip_id}/download` | Download single clip | ✅ Live |
| `POST` | `/api/assets/music` | Upload a music track for M6 composition | ✅ Ready |
| `POST` | `/api/assets/branding/logo` | Upload the StarHoop.ai brand logo | ✅ Ready |
| `POST` | `/api/assets/players/photo` | Upload a player photo and attach it to `photo_url` | ✅ Ready |
| `GET` | `/health/` | Health check | ✅ Live |

---

## Database Schema (PostgreSQL)

**Core tables:**
- **video_jobs** — Job lifecycle, status, frame/progress metrics.
- **detection_frames** — Per-frame detections JSON.
- **jersey_detections** — Aggregated jersey mapping by track.
- **action_detections** — Action windows and confidence.
- **players / teams / coaches** — Roster and organization entities.

**M5 tables:**
- **highlight_reels** — Reel artifacts (`scope`, `player_id`, output metadata).
- **highlight_clips** — Per-clip event metadata and clip artifact paths.

---

## How It Works: Request Lifecycle

1. Coach uploads video via `POST /api/videos/upload`.
2. FastAPI persists a `video_jobs` row and stores source media.
3. Modal worker processes detection/tracking/classification/OCR.
4. Webhook writes structured frame and identity outputs to PostgreSQL.
5. Coach can export annotated full video.
6. Coach can trigger action recognition.
7. Coach triggers M5 highlights extraction (master or per-player).
8. System extracts/stitches clips and persists reel + clip artifacts.
9. Coach downloads final reel or individual clips.

---

## Environment Configuration (.env)

Use `.env.example` as the source template and provide environment-specific values.

```env
# PostgreSQL
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/starhoop
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/starhoop

# App
APP_ENV=development

# Modal orchestration
ENABLE_MODAL_ORCHESTRATION=true
MODAL_APP_NAME=hoopstar-cv
MODAL_CLS_NAME=BasketballModels

# Webhook
WEBHOOK_BASE_URL=https://<your-ngrok-or-domain>
WEBHOOK_HMAC_SECRET=<shared-secret>

# Cloudflare R2
R2_ACCOUNT_ID=<account>
R2_ACCESS_KEY_ID=<key>
R2_SECRET_ACCESS_KEY=<secret>
R2_BUCKET=<bucket>
R2_ENDPOINT_URL=
R2_PRESIGN_EXPIRY_SEC=3600
```

---

## Development Workflow

See `STARTUP_GUIDE.md` for full terminal-by-terminal startup flow.

```bash
# Start services
docker compose up -d

# Run migrations
PYTHONPATH=src python -m alembic upgrade head

# Health
curl http://localhost:8000/health/
```

### Asset Upload Locations

- Music files are stored under `uploads/assets/music/`.
- Brand logo files are stored under `uploads/assets/branding/`.
- Player photos are stored under `uploads/assets/players/team_{team_id}/jersey_{jersey_number}/` and the saved path is written to `players.photo_url`.

### Example Uploads

```powershell
# Music
curl -X POST -F "file=@C:\path\to\theme.mp3" http://localhost:8000/api/assets/music

# Brand logo
curl -X POST -F "file=@C:\path\to\brand-logo.png" http://localhost:8000/api/assets/branding/logo

# Player #14 photo (replace team_id with the correct team)
curl -X POST -F "team_id=1" -F "jersey_number=14" -F "file=@C:\path\to\player14.jpg" http://localhost:8000/api/assets/players/photo
```

### M5 Validation Quick Path (job 16 example)

```powershell
# 1) actions
$actions = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/videos/16/actions/auto?min_confidence=0.6&max_actions=200"

# 2) master reel
$master = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/videos/16/highlights/extract?source=clean"

# 3) boxed single-player reel
$player = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/videos/16/highlights/extract?source=annotated&player_id=1"

# 4) download
Invoke-WebRequest -Uri ("http://localhost:8000/api/videos/16/highlights/" + $player.reel_id + "/download") -OutFile "C:\Users\einav\OneDrive\Desktop\job16_player_boxed.mp4"
```

---

## Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| Modal GPU workers | Serverless scaling and reproducible inference runtime |
| Cloudflare R2 | S3-compatible object storage with cost-efficient transfer |
| FastAPI | Strong async API/webhook ergonomics |
| PostgreSQL | ACID + robust relational model for analytics artifacts |
| Docker Compose | Reproducible local stack and easy reset/testing |
| ffmpeg extraction/stitching | Deterministic media pipeline for M5 |

---

## Known Limitations & Next Work

- M6 composition layer not implemented yet (next milestone).
- Advanced made/missed outcome semantics can still be improved.
- Multi-camera and live-stream operation are out of current scope.
- Production hardening opportunities remain (authz, quotas, observability, billing).

---

## Contributing & Code Style

- Python 3.12, FastAPI conventions, SQLAlchemy ORM.
- Alembic for schema migration.
- Black + lint checks.
- Pytest for unit/integration validation.

---

## Contact & License

- Created: June 2026
- Repo: GitHub (link)
- License: set your intended license (MIT, Apache-2.0, or proprietary)

---

**Last updated:** June 15, 2026 — Milestones 1–5 complete, Milestone 6 next.
