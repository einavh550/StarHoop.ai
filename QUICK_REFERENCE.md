# StarHoop.ai Quick Reference

## 1) Start and Stop

Start full stack:

```powershell
docker compose up --build
```

Stop stack:

```powershell
docker compose down
```

Check containers:

```powershell
docker ps
```

## 2) Health and Migrations

Health:

```powershell
curl.exe "http://localhost:8000/health/"
```

Migrations:

```powershell
docker compose exec api alembic upgrade head
docker compose exec api alembic current
```

## 3) Tests

Run full tests in container:

```powershell
docker compose exec api pytest -v
```

Run local tests (if using venv):

```powershell
.venv\Scripts\Activate.ps1
pytest -v
```

## 4) DB Access

Open DB shell:

```powershell
docker compose exec db psql -U postgres -d starhoop
```

Useful psql commands:

```sql
\dt
\d video_jobs
\d detection_frames
\q
```

## 5) Milestone 2 Video Flow

Upload:

```powershell
curl.exe -X POST "http://localhost:8000/api/videos/upload" `
  -F "team_id=<team_id>" `
  -F "file=@C:\Users\einav\OneDrive\Desktop\basketballVideo.mp4"
```

Poll status:

```powershell
curl.exe "http://localhost:8000/api/videos/<job_id>"
```

Quick DB verify:

```powershell
docker compose exec db psql -U postgres -d starhoop -c "SELECT id, status, total_frames, processed_frames FROM video_jobs ORDER BY id DESC LIMIT 5;"
docker compose exec db psql -U postgres -d starhoop -c "SELECT COUNT(*) FROM detection_frames WHERE video_job_id=<job_id>;"
```

## 6) Common Issues

`team_id does not exist`
- Insert coach/team first and use a valid team ID.

`status = failed`
- Inspect logs:

```powershell
docker compose logs -f api
```

`localhost:8000 not reachable`
- Verify `api` container is running and port 8000 is free.

`psql multiline prompt (starhoop-#)`
- Cancel with Ctrl+C, then exit with `\q`.

## 7) Milestone Scope Reminder

Milestone 2 now:
- Upload + process + persist detections
- ByteTrack track_id continuity

Milestone 3 later:
- Jersey OCR and mapping track results to real players
