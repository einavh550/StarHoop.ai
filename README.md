# StarHoop.ai

StarHoop.ai is an AI pipeline for youth basketball coaches. The current implementation supports Milestone 2 core flow: upload a game video, run player detection/tracking, and persist frame-level results.

## Current Milestone Status

- Milestone 1: Complete (schema, migrations, base API, tests)
- Milestone 2: Implemented and validated on real video (upload -> processing -> completed)
- Milestone 3: Planned (jersey OCR + player mapping)
- Milestone 4+: Planned

Important: `track_id` is a tracker identity assigned by ByteTrack. It is not jersey identity.

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

## Milestone 2 API

- `POST /api/videos/upload`
- `GET /api/videos/{job_id}`
- `GET /health/`

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

## Local Development (Optional)

If you are not using Compose for API runtime:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:PYTHONPATH = "src"
python -m uvicorn app.main:app --reload
```

And run PostgreSQL separately (Docker or local service), then:

```powershell
alembic upgrade head
pytest -v
```

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

## License

TBD
