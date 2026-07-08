# MILESTONE 2 VALIDATION CHECKLIST

Project: StarHoop.ai
Milestone: 2 - Perception (Upload, Detection, Tracking, Persistence)
Validator: ___________________
Date: ___________________

---

## A. Prerequisites

- [ ] Docker installed and running
- [ ] Repository cloned
- [ ] Video file available (mp4 recommended)

---

## B. Start Runtime

- [ ] Start services:

```powershell
docker compose up --build
```

- [ ] API health passes:

```powershell
curl.exe "http://localhost:8000/health/"
```

Expected:

```json
{"status":"ok","database":"connected"}
```

---

## C. Schema + Tests

- [ ] Apply migrations:

```powershell
docker compose exec api alembic upgrade head
```

- [ ] Confirm current revision:

```powershell
docker compose exec api alembic current
```

- [ ] Run tests:

```powershell
docker compose exec api pytest -v
```

---

## D. Seed Team Data

- [ ] Open psql:

```powershell
docker compose exec db psql -U postgres -d starhoop
```

- [ ] Insert coach/team (adjust IDs if already present):

```sql
INSERT INTO coaches (full_name, email) VALUES ('Validation Coach', 'validation.coach@example.com') RETURNING id;
INSERT INTO teams (coach_id, name, season, logo_url) VALUES (<coach_id>, 'Validation Team', '2025-2026', NULL) RETURNING id;
\q
```

---

## E. Upload and Process Video

- [ ] Upload video:

```powershell
curl.exe -X POST "http://localhost:8000/api/videos/upload" `
  -F "team_id=<team_id>" `
  -F "file=@C:\Users\einav\OneDrive\Desktop\basketballVideo.mp4"
```

- [ ] Capture returned `job_id`.

- [ ] Poll job status until final:

```powershell
curl.exe "http://localhost:8000/api/videos/<job_id>"
```

Expected lifecycle:
- [ ] pending
- [ ] processing
- [ ] completed

Expected final checks:
- [ ] progress_percent = 100.0
- [ ] processed_frames = total_frames
- [ ] error_message = null
- [ ] processing_duration_sec exists
- [ ] throughput_fps exists

---

## F. Database Persistence Verification

- [ ] Verify job row:

```powershell
docker compose exec db psql -U postgres -d starhoop -c "SELECT id, team_id, status, total_frames, processed_frames, error_message FROM video_jobs WHERE id=<job_id>;"
```

- [ ] Verify detection rows:

```powershell
docker compose exec db psql -U postgres -d starhoop -c "SELECT COUNT(*) FROM detection_frames WHERE video_job_id=<job_id>;"
```

Expected: count > 0

- [ ] Inspect sample detection payload:

```powershell
docker compose exec db psql -U postgres -d starhoop -c "SELECT frame_number, timestamp_sec, detections_json FROM detection_frames WHERE video_job_id=<job_id> LIMIT 1;"
```

Expected: JSON entries containing bbox, confidence, and track_id.

---

## G. Pass/Fail Decision

Pass when all are true:

- [ ] Upload API works
- [ ] Job completes without runtime error
- [ ] All frames processed
- [ ] Detection frames persisted
- [ ] Health endpoint stable

Status: [ ] PASSED   [ ] FAILED
Notes:
____________________________________________________________
____________________________________________________________

---

## H. Known Milestone Boundaries

- Included in Milestone 2:
  - Person detection
  - Track IDs (ByteTrack)
  - Async processing + persistence

- Not included in Milestone 2:
  - Jersey OCR
  - Player identity mapping
  - Action recognition / highlight extraction
