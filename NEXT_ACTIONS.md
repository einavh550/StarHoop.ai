# NEXT ACTIONS - StarHoop.ai Milestone 2

## Status Snapshot

- Upload and status APIs are working.
- Real video processing reached `completed` with full frame coverage.
- ByteTrack is active.
- DeepSORT remains scaffold-only and is not required for Milestone 2 signoff.

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

## Milestone 2 Validation Flow (Teammate-Friendly)

1. Create coach and team in DB (one time):

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

## Milestone 2 Done Definition

Milestone 2 is accepted when:

1. Upload returns `202` with a valid `job_id`.
2. Job transitions to `completed`.
3. `processed_frames` equals `total_frames`.
4. Detection rows exist for that `job_id`.
5. `error_message` is null.

## Remaining Work (Not Blocking M2 Signoff)

1. Improve tracker quality for hard occlusions.
2. Implement DeepSORT adapter or formally keep ByteTrack-only strategy.
3. Add richer operational metrics if needed.

## Explicit Deferrals

- Jersey OCR and player identity mapping -> Milestone 3.
- Action recognition and clip generation -> Milestone 4/5.

## Git Release Steps

After docs are updated and reviewed:

1. Commit 1: core milestone docs.
2. Commit 2: validation and quick reference docs.
3. Commit 3: final consistency/polish (and any related runtime notes).

Push:

```powershell
git push origin main
```
