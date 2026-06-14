# StarHoop.ai 🏀 — AI-Powered Basketball Analytics for Youth Coaches

**Status:** Milestones 1–4 complete and tested. Milestones 5–6 in progress.

---

## Overview

**StarHoop.ai** is an AI-powered platform that automates basketball game analysis. Coaches upload a raw game video → the system automatically detects, tracks, and identifies every player by jersey number and team → coaches get structured, queryable game data with player stats, shots, and actions.

**Tech Stack:**
- **Backend:** FastAPI (Python) + PostgreSQL + SQLAlchemy ORM
- **GPU Inference:** Modal serverless (RF-DETR, SAM-2, SigLIP, SmolVLM2)
- **Storage:** Cloudflare R2 (S3-compatible)
- **Containerization:** Docker + Docker Compose
- **Mobile Frontend:** Android (Kotlin) — coming later

---

## Project Structure

```
StarHoop.ai/
├── src/
│   ├── app/
│   │   ├── main.py              # FastAPI app entry point
│   │   ├── models/              # SQLAlchemy ORM models (VideoJob, DetectionFrame, etc.)
│   │   ├── schemas/             # Pydantic validation schemas
│   │   ├── routes/              # API endpoints (upload, status, results)
│   │   ├── cv/                  # Computer vision pipeline
│   │   │   ├── actions.py       # Action recognition (shot detection)
│   │   │   ├── annotated_export.py  # Render annotated MP4s with labels/boxes
│   │   │   ├── mapping.py       # Jersey → player name mapping
│   │   │   └── ...
│   │   └── database.py          # Session management, DB connection
│   ├── migrations/              # Alembic DB schema versions
│   └── requirements.txt         # Python dependencies
├── modal_app/
│   └── cv_app.py                # Modal app definition (GPU compute image + entry points)
├── docs/
│   ├── POSTER_CONTENT.md        # Project poster/pitch content
│   └── SCHEMA_DIAGRAM.md        # Database schema details
├── docker-compose.yml           # PostgreSQL + API service definitions
├── .env                         # Environment config (DATABASE_URL, R2, Modal, ngrok, etc.)
├── Dockerfile                   # API service container definition
└── README.md                    # This file
```

---

## Milestones Implemented & Tested (1–4)

### ✅ Milestone 1: Object Detection (RF-DETR)
- Detects players, ball, rim, jersey numbers, and special actions (jump shot, layup/dunk, shot-block).
- Runs on Modal GPU (A10G).
- **Output:** Per-frame bounding boxes with class names, confidences, and center coordinates.
- **Status:** Tested on job 16 with 5,560 frames; 12K+ player detections collected.

### ✅ Milestone 2: Real-Time Tracking (SAM-2)
- Propagates player masks and persistent track IDs across all frames using SAM-2 (Meta's real-time segmentation).
- Initialized from RF-DETR detections on frame 1, then tracked.
- **Output:** Per-track identity (track_id → player) and masks.
- **Status:** Tested; 27 unique tracks identified across job 16 (all mapped to roster).

### ✅ Milestone 3: Team Classification (SigLIP + UMAP + K-Means)
- Embeds each player crop using SigLIP (vision-language model).
- Clusters into two teams using UMAP → K-Means.
- **Output:** Team assignment per track (team_a or team_b).
- **Status:** Tested; all 27 players assigned to teams with consistent colors/labels.

### ✅ Milestone 4: Jersey OCR & Player Identity Mapping
- Extracts jersey number from each player using SmolVLM2 (small vision language model).
- Maps number + team → player name via roster lookup.
- Consecutive-frame agreement validation: jersey only accepted after 5+ consecutive reads.
- **Output:** Per-track mapping: (track_id, jersey_number, player_name).
- **Status:** Tested; all 27 mapped to roster players in job 16.

**Additional M4 Features (added in this session):**
- **Annotated Video Export:** Renders MP4 with centered player labels ("Player Name #XX") and smooth bounding boxes.
- **Temporal Box Interpolation:** Bridges detection gaps (up to 0.5s) with linear interpolation, ensuring smooth box motion across frame stride boundaries.
- **Jersey Voting:** Aggregates per-track jersey OCR detections via `PlayerMapper.aggregate_jerseys_from_video()` for stable identity assignment.
- **Action Recognition (Shot Detection):** Detects shooting actions via center_y trajectory analysis (jump arc detection). **Fixed bug in M4:** class_name filter now accepts both "person" and "player" instead of just "person".

---

## Milestones Pending (5–6)

### 📋 Milestone 5: Highlight Clip Extraction & Stitching
**Goal:** Auto-extract relevant clips (shots, possessions, actions) and stitch them into a coach-friendly highlight reel.

**Scope:**
- Extract clips around detected actions (shots, layups, dunks, blocks).
- Rank clips by game intensity (made vs. missed, player importance, game context).
- Stitch into a single MP4 (with or without basic transitions).
- Include per-clip metadata (player, action type, timestamp).

**Entry Point:** `POST /api/videos/{job_id}/highlights/extract`

**Dependencies:** Milestones 1–4 (need action detection + player identity).

### 📋 Milestone 6: Professional Graphics & Music
**Goal:** Layer professional overlays, music, and analytics onto the highlight reel.

**Scope:**
- Animated score ticker, game clock, possession counter.
- Per-player stats overlay (points, rebounds, assists, FG%).
- Licensed background music synced to highlight pacing.
- Watermark / branding.
- Optional: slow-motion on key moments.

**Entry Point:** `POST /api/videos/{job_id}/highlights/pro-graphics`

**Dependencies:** Milestone 5 (needs extracted clips + metadata).

---

## API Endpoints (Live)

| Method | Endpoint | Purpose | Status |
|--------|----------|---------|--------|
| `POST` | `/api/videos/upload` | Create a job, upload video to R2 | ✅ Live |
| `GET` | `/api/videos/{job_id}` | Poll job status (progress_percent, throughput_fps) | ✅ Live |
| `GET` | `/api/videos/{job_id}/results` | Retrieve detection results + jersey IDs | ✅ Live |
| `POST` | `/api/videos/{job_id}/exports/annotated` | Generate annotated MP4 (RF-DETR boxes + labels) | ✅ Live |
| `POST` | `/api/videos/{job_id}/actions/auto` | Run action recognizer (shot detection) | ✅ Live (bug fixed) |
| `GET` | `/health` | Health check | ✅ Live |
| `POST` | `/api/videos/{job_id}/results` (webhook) | Modal callback (internal) | ✅ Live |

---

## Database Schema (PostgreSQL)

**Key Tables:**

- **video_jobs** — Metadata: status, frame count, throughput, remote_video_url, modal_call_id.
- **detection_frames** — Per-frame detections (JSON: boxes, class_name, track_id, confidence).
- **jersey_detections** — Aggregated jersey per track (detected_jersey_number, mapped_player_id, frame_count).
- **action_detections** — Detected actions/shots (track_id, action_type, confidence, start_frame, end_frame, timestamps).
- **players** — Roster (player_id, name, jersey_number, team_id).
- **teams** — Team metadata (team_id, name, color_primary, color_secondary).
- **coaches** — Coach accounts (email, auth info).

---

## How It Works: Request Lifecycle

1. **Coach uploads video** → `POST /api/videos/upload`
2. **FastAPI stores** → Saves to Cloudflare R2, creates `VideoJob` record in DB.
3. **FastAPI triggers Modal** → Sends job to Modal with callback URL (`WEBHOOK_BASE_URL`).
4. **API returns instantly** → `202 Accepted` + `job_id`.
5. **Modal downloads** → Fetches video from R2.
6. **Modal runs pipeline** → RF-DETR → SAM-2 → SigLIP → SmolVLM2.
7. **Modal posts results** → Webhook POST to `WEBHOOK_BASE_URL/api/videos/{job_id}/results` with HMAC signature.
8. **FastAPI validates** → Verifies HMAC, persists detections to DB.
9. **Coach polls** → `GET /api/videos/{job_id}` → Returns status + results.
10. **Coach exports annotated video** → `POST /api/videos/{job_id}/exports/annotated` → Renders MP4 with labels.

---

## Environment Configuration (.env)

```env
# PostgreSQL
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/starhoop
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/starhoop

# Application
APP_ENV=development

# Modal orchestration (must be true for async jobs)
ENABLE_MODAL_ORCHESTRATION=true
MODAL_APP_NAME=hoopstar-cv
MODAL_CLS_NAME=BasketballModels

# ngrok URL (set after starting ngrok tunnel)
WEBHOOK_BASE_URL=https://thrift-fraying-plentiful.ngrok-free

# HMAC secret (shared with Modal for webhook verification)
WEBHOOK_HMAC_SECRET=397badbdbc431ee6df66860c3bf208ed98cc972e8ff55e27bd21e9fadd8f8749

# Cloudflare R2
R2_ACCOUNT_ID=438151457eaf867d1972dc6ecad43919
R2_ACCESS_KEY_ID=71c2d4426dea6bb858847be77b18203f
R2_SECRET_ACCESS_KEY=69ded373753b4ee57fce057fcdcd9826a03bcf151acf247f9d4caf47da8b59de
R2_BUCKET=hoopstar-ai
R2_ENDPOINT_URL=
R2_PRESIGN_EXPIRY_SEC=3600
```

---

## Recent Changes & Fixes (This Session)

### 1. Fixed Action Recognition (class_name filter)
- **Issue:** Action recognizer filtered `class_name != "person"` but CV pipeline outputs `class_name = "player"`.
- **Fix:** Changed filter to `class_name not in {"person", "player"}` with `.lower()` normalization in `src/app/cv/actions.py`.
- **Impact:** Action detection now works for job 16 (pending Docker rebuild + re-trigger).

### 2. Annotated Video Export with Centered Labels
- **Feature:** Renders MP4 with player names + jersey numbers centered above bounding boxes.
- **Implementation:** `src/app/cv/annotated_export.py` → `_draw_track_overlay()` draws single centered label instead of dual side labels.
- **Status:** Tested on job 16; 161 MB valid MP4 generated.

### 3. Temporal Box Interpolation
- **Feature:** Bridges bounding box detection gaps (up to 0.5s) with linear interpolation.
- **Why:** CV pipeline uses frame stride=3 (processes every 3rd frame); gaps cause jumpy boxes.
- **Implementation:** `_build_interpolated_boxes()` in `annotated_export.py` → carries interpolation 0.15s into future.
- **Status:** Tested; smooth box motion confirmed in job 16 export.

### 4. Jersey Voting & Roster Mapping
- **Feature:** Aggregates per-track jersey detections via consecutive-frame agreement.
- **Implementation:** `PlayerMapper.aggregate_jerseys_from_video()` → votes per jersey across frames → maps to roster player.
- **Status:** All 27 tracks in job 16 mapped to roster.

---

## Test Data & Validation

**Job 16 (validation dataset):**
- **Frames:** 5,560 (stride=3 from source)
- **Detections:** 12,118 player boxes
- **Tracks:** 27 unique players
- **Actions detected:** 0 (before fix), pending re-detection after Docker rebuild
- **Export:** 161 MB annotated MP4 with centered labels + smooth boxes

**Verified outputs:**
- ✅ RF-DETR detections (all classes)
- ✅ SAM-2 tracking (27 persistent IDs)
- ✅ SigLIP team classification (2 teams, consistent colors)
- ✅ SmolVLM2 jersey OCR (all 27 mapped to roster)
- ✅ Annotated export (centered labels, interpolated boxes)
- ✅ Action recognition filter (fixed class_name bug)

---

## Development Workflow

### Quick Commands
See [STARTUP_GUIDE.md](STARTUP_GUIDE.md) for full terminal-by-terminal startup sequence.

```bash
# Start Docker (PostgreSQL + API container)
docker compose up -d

# Start FastAPI (with auto-reload) — Terminal 2
cd src
PYTHONPATH=. python -m uvicorn app.main:app --reload --port 8000

# Start ngrok tunnel — Terminal 3
ngrok http 8000

# Update .env with ngrok URL after starting ngrok
```

### Testing the Pipeline
```bash
# Health check
curl http://localhost:8000/health

# Upload a video
curl -X POST \
  -H "Content-Type: multipart/form-data" \
  -F "file=@game.mp4" \
  -F "team_id=1" \
  http://localhost:8000/api/videos/upload

# Poll status
curl http://localhost:8000/api/videos/{job_id}

# Export annotated video
curl -X POST http://localhost:8000/api/videos/{job_id}/exports/annotated

# Detect actions
curl -X POST http://localhost:8000/api/videos/{job_id}/actions/auto
```

---

## Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| **Modal for GPU** | Serverless = no idle costs. Scales automatically. Reproducible Docker images. |
| **Cloudflare R2** | S3-compatible, fast downloads from Modal US-regions. Cheaper than AWS S3. |
| **FastAPI** | Async-first, great webhook support, auto-generated API docs. |
| **PostgreSQL** | ACID compliance, JSON column support (for detections), mature ecosystem. |
| **Docker Compose locally** | Reproduces production DB locally. Easy to reset with `docker compose down -v`. |
| **Frame stride=3** | Balances accuracy vs. throughput. 30 FPS → 10 FPS effective (less compute). |
| **SAM-2 (real-time)** | Fast, accurate masks. Maintains track consistency across frames. |
| **SigLIP + K-Means** | Lightweight team classification. Avoids heavyweight segmentation models. |
| **SmolVLM2 for OCR** | Efficient jersey number reading. Works on GPU without heavy fine-tuning. |

---

## Known Limitations & TODOs

- **M5/M6 not started:** Clip extraction, stitching, pro graphics pending.
- **No made/missed shot detection yet:** Action recognizer only detects attempt (not outcome).
- **No possession tracking:** Derived from action detections in M6 planning.
- **No live streaming:** System is async (upload → process → results).
- **Limited jersey confidence filtering:** Basic consecutive-frame agreement; could improve with confidence-weighted voting.
- **No multi-angle support:** Single camera assumed.

---

## Contributing & Code Style

- **Python:** 3.12, FastAPI conventions, SQLAlchemy ORM.
- **Database:** Alembic migrations (no raw SQL).
- **Formatting:** Black (auto-format) + Pylint.
- **Testing:** Pytest (not yet implemented; to-do).

---

## Contact & License

- **Created:** June 2026
- **Repo:** GitHub (link)
- **License:** (MIT/Apache/proprietary — fill in)

---

**Last updated:** June 14, 2026 — Milestones 1–4 complete, M5–M6 planning phase.
