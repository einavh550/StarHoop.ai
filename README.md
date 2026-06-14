git # StarHoop.ai

AI-powered basketball video analysis for coaches.

Current status:
- Milestones 1-5 complete and validated end-to-end.
- Milestone 6 pending (polish/composition layer: intro cards, transitions, music, branding).

## What The System Does

1. Upload a game video.
2. Run CV pipeline (detection, tracking, team classification, jersey mapping).
3. Persist structured detections/actions in PostgreSQL.
4. Generate:
- Annotated full-video export.
- Highlight reels (master all-players reel and optional per-player reel).

## Tech Stack

- Backend: FastAPI + SQLAlchemy + Alembic
- Database: PostgreSQL
- CV/Inference: Modal GPU workers (RF-DETR, SAM-2, SigLIP, SmolVLM2)
- Storage: Cloudflare R2 (S3-compatible)
- Video processing: ffmpeg
- Local orchestration: Docker Compose

## Milestones

### Milestone 1-4 (Complete)

- Detection, tracking, team classification, jersey OCR mapping.
- Action detection endpoint for auto shot-attempt extraction.
- Annotated full-video export.

### Milestone 5 (Complete)

- Highlight event derivation from action + frame-level signals.
- Clip extraction and reel stitching via ffmpeg.
- New persistence tables:
- highlight_reels
- highlight_clips
- Hybrid output model:
- Master reel (all events, all players).
- Optional minimal per-player reel from same pipeline.
- Annotated source support for highlights:
- source=clean: no overlays.
- source=annotated: overlays present.
- Single-player annotated mode:
- For per-player + source=annotated, only the selected player is boxed/labeled.
- Other players remain unannotated.

### Milestone 6 (Pending)

Planned: professional composition layer on top of per-player reels (intro cards, overlays, transitions, music, branding).

## API Endpoints

### Health

- GET /health/

### Video jobs

- POST /api/videos/upload
- GET /api/videos/{job_id}
- GET /api/videos/{job_id}/results

### Actions

- POST /api/videos/{job_id}/actions/auto

### Annotated exports

- POST /api/videos/{job_id}/exports/annotated
- GET /api/videos/{job_id}/exports/annotated/{export_id}
- GET /api/videos/{job_id}/exports/annotated/{export_id}/download

### Highlights (M5)

- POST /api/videos/{job_id}/highlights/extract
Query params:
- source=clean|annotated
- player_id optional
- max_clips optional
- min_confidence optional
- event_types optional
- pad_pre_sec optional
- pad_post_sec optional

- GET /api/videos/{job_id}/highlights/{reel_id}
- GET /api/videos/{job_id}/highlights/{reel_id}/download
- GET /api/videos/{job_id}/highlights/{reel_id}/clips/{clip_id}/download

## Local Setup

Prerequisites:
- Docker Desktop
- Python 3.12 + virtualenv

1. Install dependencies

```powershell
Set-Location "c:\Users\einav\OneDrive\Desktop\HoopStar.ai\StarHoop.ai"
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. Configure environment

- Copy .env.example to .env and fill values.
- Do not commit secrets.

3. Run database + API container

```powershell
docker compose up -d
```

4. Run migrations

```powershell
$env:PYTHONPATH='src'
python -m alembic upgrade head
```

5. Verify health

```powershell
iwr http://localhost:8000/health/ -UseBasicParsing
```

Expected content:
- {"status":"ok","database":"connected"}

## M5 Quick Validation

Example using job 16:

1. Generate actions

```powershell
$actions = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/videos/16/actions/auto?min_confidence=0.6&max_actions=200"
$actions
```

2. Generate master reel

```powershell
$master = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/videos/16/highlights/extract?source=clean"
$master
```

3. Generate boxed single-player reel (example player_id=1)

```powershell
$player = Invoke-RestMethod -Method Post -Uri "http://localhost:8000/api/videos/16/highlights/extract?source=annotated&player_id=1"
$player
```

4. Download reel

```powershell
Invoke-WebRequest -Uri ("http://localhost:8000/api/videos/16/highlights/" + $player.reel_id + "/download") -OutFile "C:\Users\einav\OneDrive\Desktop\job16_player_boxed.mp4"
```

## Data Model (Core)

- video_jobs: upload/process lifecycle.
- detection_frames: frame-level detections JSON.
- jersey_detections: aggregated jersey mapping by track.
- action_detections: detected actions and timing windows.
- highlight_reels: stitched output artifacts.
- highlight_clips: per-clip metadata/artifacts.

## Notes

- For source=annotated and player_id set, highlights use a player-targeted annotated source render.
- This keeps only the selected player boxed in the final per-player reel.
- Master annotated reels keep normal all-player annotation behavior.

## License

Set your intended license in this section (MIT, Apache-2.0, or proprietary).
