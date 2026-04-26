# StarHoop.ai

**StarHoop.ai**: An AI-powered system for youth basketball coaches to automatically generate and share personalized player highlights from amateur smartphone footage using Computer Vision and Deep Learning.

---

## Project Overview

**Target Audience**: Youth basketball coaches (players aged 6-13)  
**Goal**: Automate extraction of personalized player highlights from amateur footage recorded on a smartphone tripod, enabling coaches to provide parents with high-quality clips of their children's best moments.

**Identification**: Strictly based on **Jersey Number Recognition (OCR)**. Profile photos are for UX/UI only.  
**Infrastructure**: PostgreSQL (Docker, localhost:5432, ARM64-optimized), Firebase (media storage).

---

## Tech Stack

- **Backend**: Python, FastAPI, SQLAlchemy, Alembic  
- **Computer Vision**: YOLOv8 (detection), DeepSORT/ByteTrack (tracking), 3D CNNs (action recognition)  
- **Frontend**: Android Studio (Kotlin)  
- **Data Management**: PostgreSQL (relational), Firebase (blob storage)

---

## Development Milestones

- ✅ **MILESTONE 1**: Infrastructure – Modular Python structure, PostgreSQL schema, validation tests  
- 🔄 **MILESTONE 2**: Perception – YOLOv8 + Tracking (in progress)  
- ⏳ **MILESTONE 3**: Identity – Jersey OCR + DB mapping  
- ⏳ **MILESTONE 4**: Action Recognition – 3D CNN spatio-temporal analysis  
- ⏳ **MILESTONE 5**: Video Engine – Temporal segmentation and clipping  
- ⏳ **MILESTONE 6**: Full Integration – Kotlin mobile UI + API connection

---

## MILESTONE 1: Setup & Validation

### 1. Prerequisites

- **Python 3.13+** (virtual environment recommended)
- **PostgreSQL** running in Docker at `localhost:5432` (see below for setup)
- **Git** for version control

### 2. PostgreSQL Setup (Docker)

If you don't have PostgreSQL running yet, use Docker:

```powershell
docker run --name starhoop-postgres -e POSTGRES_PASSWORD=your_password -e POSTGRES_DB=starhoop -p 5432:5432 -d postgres:16-alpine
```

**Important**: Replace `your_password` with your actual PostgreSQL password.

### 3. Clone & Install Dependencies

```powershell
git clone <repository-url>
cd StarHoop.ai
python -m venv .venv
.venv\Scripts\Activate.ps1   # or `.venv\Scripts\activate` on cmd
pip install -r requirements.txt
```

### 4. Configure Environment

Copy the example environment file and **update credentials**:

```powershell
cp .env.example .env
```

Edit [.env](.env) and set your actual PostgreSQL password:

```ini
DATABASE_URL=postgresql+psycopg://postgres:your_password@localhost:5432/starhoop
TEST_DATABASE_URL=postgresql+psycopg://postgres:your_password@localhost:5432/starhoop
APP_ENV=development
```

### 5. Run Database Migrations

Apply the initial schema migration:

```powershell
alembic upgrade head
```

You should see:
```
INFO  [alembic.runtime.migration] Running upgrade  -> 20260224_000001, initial starhoop schema
```

### 6. Run Tests

**Unit tests** (no DB connection required):

```powershell
pytest tests/unit -v
```

Expected: **5 passed**

**Integration tests** (requires live PostgreSQL with correct credentials):

```powershell
pytest tests/integration -v
```

Expected (if DB configured): **5 passed**  
Expected (if DB unavailable): **5 skipped** with message `"Integration DB unavailable: ..."`

**Run all tests**:

```powershell
pytest -v
```

### 7. Start the API Server

```powershell
uvicorn app.main:app --reload
```

Visit [http://localhost:8000/health/](http://localhost:8000/health/) – you should see:

```json
{"status": "ok", "database": "connected"}
```

Visit [http://localhost:8000/docs](http://localhost:8000/docs) for interactive API documentation.

---

## Project Structure

```
StarHoop.ai/
├── src/
│   └── app/
│       ├── api/
│       │   └── routes/
│       │       ├── health.py         # Health check endpoint
│       │       └── videos.py         # Video upload and job status endpoints
│       ├── core/
│       │   └── config.py            # Settings and environment loading
│       ├── cv/
│       │   ├── detection.py         # YOLOv8 detector wrapper
│       │   ├── tracking.py          # ByteTrack + DeepSORT scaffold
│       │   ├── video_processor.py   # Processing orchestration
│       │   ├── storage.py           # Persistent upload storage helpers
│       │   └── schemas.py           # CV/API schemas
│       ├── db/
│       │   ├── base.py              # SQLAlchemy Base
│       │   ├── session.py           # Engine and SessionLocal
│       │   ├── schema.sql           # Reference SQL DDL
│       │   └── models/
│       │       ├── coach.py         # Coach model
│       │       ├── team.py          # Team model
│       │       ├── player.py        # Player model (with jersey number)
│       │       ├── highlight.py     # Highlight model
│       │       ├── video_job.py     # Async processing jobs
│       │       └── detection_frame.py # Frame-level detections
│       └── main.py                  # FastAPI app factory
├── alembic/
│   ├── versions/
│   │   ├── 20260224_000001_init_schema.py   # Initial migration
│   │   └── 20260307_000002_milestone2_video_jobs.py  # Milestone 2 migration
│   └── env.py                       # Migration environment
├── tests/
│   ├── unit/
│   │   ├── test_config_and_engine.py
│   │   └── test_health_route.py
│   ├── integration/
│   │   └── test_schema_integrity.py
│   └── conftest.py                  # Pytest fixtures (DB session)
├── alembic.ini                       # Alembic configuration
├── pytest.ini                        # Pytest configuration
├── requirements.txt                  # Python dependencies
├── .env.example                      # Example environment variables
└── README.md                         # This file
```

---

## Database Schema (MILESTONE 1)

### Hierarchy

**Coach → Team → Player → Highlight**

### Tables

- **`coaches`**: `id`, `full_name`, `email` (UNIQUE), `created_at`
- **`teams`**: `id`, `coach_id` (FK), `name`, `logo_url`, `season`, `created_at`  
  - UNIQUE: (`coach_id`, `name`, `season`)
- **`players`**: `id`, `team_id` (FK), `full_name`, `jersey_number`, `photo_url`, `birth_year`, `created_at`  
  - UNIQUE: (`team_id`, `jersey_number`)  
  - CHECK: `jersey_number >= 0 AND jersey_number <= 99`
- **`highlights`**: `id`, `player_id` (FK), `video_url`, `event_type`, `event_timestamp_sec`, `source_video_id`, `captured_at`, `created_at`  
  - CHECK: `event_timestamp_sec >= 0`

### Indexes

- `ix_players_team_id_jersey_number` on `players(team_id, jersey_number)`
- `ix_highlights_player_id_captured_at` on `highlights(player_id, captured_at)`

---

## Validation Checklist (MILESTONE 1)

- [x] Modular Python package structure (`src/app`)
- [x] PostgreSQL schema with FK cascade and constraints
- [x] Alembic migration generated and tested
- [x] Unit tests validate config, engine, metadata, and health route (5/5)
- [x] Integration tests validate schema integrity against live DB (5/5 when DB configured, gracefully skip otherwise)
- [x] FastAPI health endpoint returns `{"status": "ok", "database": "connected"}`
- [x] README with clear setup and validation instructions

---

## Milestone 2 (Current Implementation)

### Implemented

- Async video ingestion endpoint: `POST /api/videos/upload`
- Job status endpoint: `GET /api/videos/{job_id}`
- New persistence tables: `video_jobs`, `detection_frames`
- ByteTrack-first tracking implementation with DeepSORT scaffold adapter
- CV processing orchestrator for frame extraction and per-frame persistence
- Expanded automated tests (unit + integration)

### API Endpoints

- `GET /health/` - Health check
- `POST /api/videos/upload` - Upload video and start async processing
- `GET /api/videos/{job_id}` - Fetch processing status and progress

---

## Next Steps (Remaining Milestone 2 Work)

- Install full CV runtime dependencies (`ultralytics`, `opencv-python`, `torch`, `torchvision`) on all target environments
- Improve tracker quality and complete DeepSORT adapter implementation
- Add richer progress metrics and processing telemetry
- Add end-to-end smoke tests with real sample videos

---

## Contributing

This is a Computer Science final project. Contributions are welcome after MILESTONE 1 validation is complete.

---

## License

TBD
