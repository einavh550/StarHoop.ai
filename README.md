# StarHoop.ai

StarHoop.ai is an AI-assisted basketball analytics system for youth coaches. On this branch, Google Colab performs the heavy GPU inference while the local FastAPI app handles ingestion, persistence, and downstream queries.

## Project Overview

Target audience: youth basketball coaches (players aged 6-13).
Goal: accept Colab-generated detections, persist them in PostgreSQL, and serve job status and mapping views from the local API.

Identification target: jersey number recognition and player identity mapping from Colab-ingested results.
Infrastructure: PostgreSQL (Docker) for persistence and ngrok for secure Colab-to-local API tunneling.

## Tech Stack

- Backend: Python, FastAPI, SQLAlchemy, Alembic
- AI Execution: Google Colab + GPU runtime for detection, tracking, and jersey recognition
- Frontend: Android Studio (Kotlin)
- Data Management: PostgreSQL (relational)

## Current Branch Focus

- Colab generates detections, tracks, team labels, jersey numbers, and player names.
- The local API receives batched frame payloads at `POST /api/videos/{job_id}/colab-detections`.
- PostgreSQL stores the ingested results in `video_jobs`, `detection_frames`, and `jersey_detections`.
- Player mapping and action endpoints operate on stored data rather than running local CV inference.

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

## Local API Surface

### Implemented

- Upload endpoint for creating jobs: `POST /api/videos/upload`
- Colab batch ingestion endpoint: `POST /api/videos/{job_id}/colab-detections`
- Job status endpoint: `GET /api/videos/{job_id}`
- Persistence tables: `video_jobs`, `detection_frames`
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

## Smoke Test Criteria

The branch is considered healthy when all are true:

1. Upload endpoint returns `202` with a `job_id`.
2. Colab batch ingestion returns `202` for a valid job.
3. Detection rows exist in `detection_frames` for the job.
4. Job status can be queried successfully.

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

## Historical Baseline

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
|  |  |- cv/storage.py
|  |  |- cv/schemas.py
|  |  |- cv/mapping.py
|  |  |- cv/actions.py
|  |  |- cv/annotated_export.py
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

## Database Schema

Hierarchy:
- Coach -> Team -> Player -> Highlight

Current data flow additions:
- VideoJob -> DetectionFrame

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

This is a Computer Science final project. Keep changes aligned with the current Colab-first branch architecture.

## License

TBD
