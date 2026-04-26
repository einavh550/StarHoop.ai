# StarHoop.ai

StarHoop.ai is an AI-powered system for youth basketball coaches to automatically generate and share personalized player highlights from amateur smartphone footage using Computer Vision and Deep Learning.

## Project Overview

Target audience: youth basketball coaches (players aged 6-13).
Goal: automate extraction of personalized player highlights so coaches can provide parents with high-quality clips.

Identification target: jersey number recognition (OCR). Profile photos are for UX only.
Infrastructure: PostgreSQL (Docker) and Firebase (media storage in later milestones).

## Tech Stack

- Backend: Python, FastAPI, SQLAlchemy, Alembic
- Computer Vision: YOLOv8 (detection), DeepSORT/ByteTrack (tracking), 3D CNNs (planned)
- Frontend: Android Studio (Kotlin)
- Data Management: PostgreSQL (relational), Firebase (blob storage)

## Development Milestones

- Milestone 1: Infrastructure - modular Python structure, PostgreSQL schema, validation tests
- Milestone 2: Perception - YOLOv8 + tracking
- Milestone 3: Identity - jersey OCR + DB mapping
- Milestone 4: Action recognition - spatio-temporal analysis
- Milestone 5: Video engine - temporal segmentation and clipping
- Milestone 6: Full integration - Kotlin mobile UI + API connection

## Current Milestone Status

- Milestone 1: ✅ Complete (schema, migrations, base API, tests)
- Milestone 2: ✅ Complete (YOLOv8 + ByteTrack detection + tracking, persistence)
- Milestone 3 (Phase 1): ✅ Complete (Jersey OCR extraction via PaddleOCR)
- Milestone 3 (Phase 2): ✅ Complete (Player identity mapping - jersey_detections table + auto-mapping endpoint)
- Milestone 4: Planned (Action recognition - spatio-temporal analysis)
- Milestone 5: Planned (Video clipping engine)
- Milestone 6: Planned (Mobile integration)

Important: `track_id` is a tracker identity assigned by ByteTrack. Jersey numbers are recognized via PaddleOCR in M3P1 and mapped to Player records in M3P2.

## Quick Start (Recommended: Docker Compose)

1. Start stack:

```powershell
docker compose up --build
```

2. In another terminal, verify API + DB connectivity:

```powershell
curl.exe "http://localhost:8000/health/"
```

Expected:

```json
{"status":"ok","database":"connected"}
```

3. Apply migrations (first run or after schema changes):

```powershell
docker compose exec api alembic upgrade head
```

4. Run tests in container:

```powershell
docker compose exec api pytest -v
```

## Milestone 2 (Current Implementation)

### Implemented

- Async video ingestion endpoint: `POST /api/videos/upload`
- Job status endpoint: `GET /api/videos/{job_id}`
- Persistence tables: `video_jobs`, `detection_frames`
- ByteTrack-first tracking with DeepSORT scaffold
- CV processing orchestrator for frame extraction and per-frame persistence
- Processing metrics in status response: `progress_percent`, `processing_duration_sec`, `throughput_fps`

### API Endpoints

- `GET /health/`
- `POST /api/videos/upload`
- `GET /api/videos/{job_id}`

### Upload a video

```powershell
curl.exe -X POST "http://localhost:8000/api/videos/upload" `
  -F "team_id=<your_team_id>" `
  -F "file=@C:\Users\einav\OneDrive\Desktop\basketballVideo.mp4"
```

Expected response shape:

```json
{
  "job_id": 1,
  "status": "pending",
  "message": "Video queued for processing"
}
```

### Poll status

```powershell
curl.exe "http://localhost:8000/api/videos/<job_id>"
```

Expected lifecycle:
- `pending` -> `processing` -> `completed`
- `processed_frames` increases until it equals `total_frames`
- `progress_percent` reaches `100.0`
- `processing_duration_sec` and `throughput_fps` are present

## Milestone 2 Acceptance Criteria

Milestone 2 is considered valid when all are true:

1. Upload endpoint returns `202` with a `job_id`.
2. Job reaches `completed` with `error_message = null`.
3. `processed_frames == total_frames` at completion.
4. Detection rows exist in `detection_frames` for the job.

Tip: if `team_id` does not exist, insert coach/team first and reuse the returned team ID.

## Database Verification Commands

```powershell
docker compose exec db psql -U postgres -d starhoop -c "SELECT id, status, total_frames, processed_frames, error_message FROM video_jobs ORDER BY id DESC LIMIT 3;"
```

```powershell
docker compose exec db psql -U postgres -d starhoop -c "SELECT COUNT(*) AS detection_rows FROM detection_frames WHERE video_job_id=<job_id>;"
```

```powershell
docker compose exec db psql -U postgres -d starhoop -c "SELECT frame_number, timestamp_sec, detections_json FROM detection_frames WHERE video_job_id=<job_id> LIMIT 1;"
```

## MILESTONE 1: Setup and Validation (Historical Baseline)

### 1. Prerequisites

- Python 3.13+ (virtual environment recommended)
- PostgreSQL running in Docker at localhost:5432 (for local non-compose flow)
- Git

### 2. PostgreSQL Setup (Docker)

```powershell
docker run --name starhoop-postgres -e POSTGRES_PASSWORD=your_password -e POSTGRES_DB=starhoop -p 5432:5432 -d postgres:16-alpine
```

### 3. Clone and Install Dependencies

```powershell
git clone <repository-url>
cd StarHoop.ai
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. Configure Environment

```powershell
cp .env.example .env
```

Edit `.env` and set DB credentials.

### 5. Run Migrations

```powershell
alembic upgrade head
```

### 6. Run Tests

```powershell
pytest -v
```

### 7. Start API

```powershell
uvicorn app.main:app --reload
```

## Project Structure

```text
StarHoop.ai/
|- src/
|  |- app/
|  |  |- api/routes/health.py
|  |  |- api/routes/videos.py
|  |  |- core/config.py
|  |  |- cv/detection.py
|  |  |- cv/tracking.py
|  |  |- cv/video_processor.py
|  |  |- cv/storage.py
|  |  |- cv/schemas.py
|  |  |- db/base.py
|  |  |- db/session.py
|  |  |- db/schema.sql
|  |  |- db/models/*.py
|  |- main.py
|- alembic/versions/
|  |- 20260224_000001_init_schema.py
|  |- 20260307_000002_milestone2_video_jobs.py
|- tests/
|  |- unit/
|  |- integration/
|- docker-compose.yml
|- Dockerfile
|- requirements.txt
|- README.md
```

## Database Schema (Milestone 1 Baseline)

Hierarchy:
- Coach -> Team -> Player -> Highlight

Milestone 2 additions:
- VideoJob -> DetectionFrame

## What Is Implemented vs Deferred

Implemented now:
- YOLOv8 person detection
- ByteTrack-based tracking IDs
- Async job lifecycle in `video_jobs`
- Frame-level persistence in `detection_frames`
- Dockerized runtime for reproducibility

Deferred to Milestone 3+:
- Jersey OCR and mapping to `players.jersey_number`
- Action recognition and highlight generation

## Next Steps (Remaining Milestone 2 Work)

- Improve tracker quality for hard occlusions
- Implement DeepSORT adapter fully or keep ByteTrack-only strategy explicitly
- Add richer operational metrics if needed

## Repository Notes

- Compose services: `api`, `db`
- DB in Compose: `postgres/postgres`, DB name `starhoop`
- Upload directory in container: `/app/uploads/videos`

## Troubleshooting

- If upload fails with team error, create valid coach/team rows first.
- If status stays `failed`, inspect API logs:

```powershell
docker compose logs -f api
```

- If migrations are missing:

```powershell
docker compose exec api alembic current
docker compose exec api alembic upgrade head
```

## Contributing

This is a Computer Science final project. Contributions are welcome after milestone validation milestones are coordinated.

## License

TBD
