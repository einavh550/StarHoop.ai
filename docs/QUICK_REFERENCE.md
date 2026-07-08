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

## 5) Colab Ingestion Flow

Start ngrok (one-time auth + tunnel):

```powershell
# take the authtoken from this path: https://dashboard.ngrok.com/get-started/setup/windows
ngrok config add-authtoken <NGROK_AUTHTOKEN> 
ngrok http 80
```

Create a job:

```powershell
curl.exe -X POST "http://localhost:8000/api/videos/upload" `
  -F "team_id=<team_id>" `
  -F "file=@C:\Users\einav\OneDrive\Desktop\basketballVideo.mp4"
```

Send a Colab batch:

```powershell
python tools/test_colab_ingest.py
```

Colab exporter helper (real detections):

```python
from tools.colab_exporter import ColabIngestClient, ColabBatchBuffer, build_frame_payload

client = ColabIngestClient(base_url="<ngrok_url>", job_id=<job_id>)
buffer = ColabBatchBuffer(client, max_frames=120, max_bytes=900_000)

# for each frame in Colab
frame_payload = build_frame_payload(frame_number, timestamp_sec, detections)
buffer.add_frame(frame_payload)

# after last frame
buffer.flush(final_batch=True)
```

Poll status:

```powershell
curl.exe "http://localhost:8000/api/videos/<job_id>"
```

If you need to point at a non-default host:

```powershell
python tools/test_colab_ingest.py --base-url "http://127.0.0.1:8000" --job-id 12
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

## 7) Branch Scope Reminder

Current branch now:
- Upload job metadata locally
- Post Colab detections into the API
- Persist frame batches in PostgreSQL
- Query mapping and action views from stored data
