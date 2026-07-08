# NEXT ACTIONS - StarHoop.ai (Colab Hybrid Branch)

## Status Snapshot

**Branch goal**: Colab performs detection, tracking, and jersey recognition; the local FastAPI app persists and serves results.

**Completed on this branch**
- Batch ingestion endpoint: `POST /api/videos/{job_id}/colab-detections`
- Local CV execution removed from the runtime path
- Docker smoke test passes against a real job

## Immediate Actions (Do First)

1. Keep Docker stack as the default runtime for team reproducibility.

```powershell
docker compose up --build
```

2. Ensure schema is current.

```powershell
docker compose exec api alembic upgrade head
```

3. Verify health.

```powershell
curl.exe "http://localhost:8000/health/"
```

4. Run tests.

```powershell
docker compose exec api pytest -v
```

## Smoke Test Flow

1. Create coach and team in DB if needed:

```powershell
docker compose exec db psql -U postgres -d starhoop
```

```sql
INSERT INTO coaches (full_name, email) VALUES ('Test Coach', 'test.coach@example.com') RETURNING id;
INSERT INTO teams (coach_id, name, season, logo_url) VALUES (<coach_id>, 'Star Hoopers', '2025-2026', NULL) RETURNING id;
\q
```

2. Upload test video:

```powershell
curl.exe -X POST "http://localhost:8000/api/videos/upload" `
  -F "team_id=<team_id>" `
  -F "file=@C:\Users\einav\OneDrive\Desktop\basketballVideo.mp4"
```

Capture the returned `job_id` and use it in the next commands.

3. Poll job status:

```powershell
curl.exe "http://localhost:8000/api/videos/<job_id>"
```

4. Confirm DB persistence:

```powershell
docker compose exec db psql -U postgres -d starhoop -c "SELECT id, status, total_frames, processed_frames, progress_percent FROM video_jobs ORDER BY id DESC LIMIT 1;"
docker compose exec db psql -U postgres -d starhoop -c "SELECT COUNT(*) FROM detection_frames WHERE video_job_id=<job_id>;"
```

## Branch Done Definition

This branch is in good shape when:

1. Upload returns `202` with a valid `job_id`.
2. Colab batch ingestion returns `202` for a valid job.
3. Detection rows exist for that `job_id`.
4. The health endpoint reports `database: connected`.

## Remaining Work

1. Decide whether to archive the historical milestone docs or leave them as reference.
2. Tighten any remaining user-facing docs that still mention the old local CV pipeline.
3. Add auth for the ngrok ingestion endpoint if the tunnel will be exposed outside your machine.

## Git Release Step

Push when ready:

```powershell
git push origin main
```
