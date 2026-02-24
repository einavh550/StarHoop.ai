# StarHoop.ai Quick Reference

## Daily Development Commands

### Activate Virtual Environment
```powershell
.venv\Scripts\Activate.ps1
```

### Run Development Server
```powershell
uvicorn app.main:app --reload
```
Access at: http://localhost:8000  
API docs: http://localhost:8000/docs

### Run Tests
```powershell
# All tests
pytest -v

# Unit tests only (no DB required)
pytest tests/unit -v

# Integration tests (requires DB)
pytest tests/integration -v

# With coverage
pytest --cov=app --cov-report=html
```

### Database Migrations

```powershell
# Create new migration (after model changes)
alembic revision --autogenerate -m "description of changes"

# Apply migrations
alembic upgrade head

# Rollback one migration
alembic downgrade -1

# Rollback all migrations
alembic downgrade base

# Show current migration version
alembic current

# Show migration history
alembic history
```

### Docker PostgreSQL Management

```powershell
# Start existing container
docker start starhoop-postgres

# Stop container
docker stop starhoop-postgres

# View logs
docker logs starhoop-postgres

# Connect to PostgreSQL CLI
docker exec -it starhoop-postgres psql -U postgres -d starhoop

# Remove container (data will be lost!)
docker rm -f starhoop-postgres
```

### Useful psql Commands (inside PostgreSQL CLI)

```sql
-- List all tables
\dt

-- Describe table structure
\d players

-- Show all constraints
\d+ players

-- List all databases
\l

-- Quit
\q
```

### Code Quality (optional, not in requirements.txt yet)

```powershell
# Format code
black src/ tests/

# Lint
ruff check src/ tests/

# Type checking
mypy src/
```

### Git Workflow

```powershell
# Check status
git status

# Stage changes
git add .

# Commit
git commit -m "Complete Milestone 1: infrastructure and schema"

# Push
git push origin main
```

---

## Environment Variables (.env)

```ini
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/starhoop
TEST_DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/starhoop
APP_ENV=development
```

---

## Project Structure Quick Reference

```
src/app/
  ├── main.py              # FastAPI app entry point
  ├── api/routes/          # API endpoints
  ├── core/config.py       # Settings
  ├── db/
  │   ├── base.py          # SQLAlchemy Base
  │   ├── session.py       # Database session
  │   └── models/          # ORM models
  └── cv/                  # (Milestone 2: Computer Vision modules)

alembic/versions/          # Database migrations
tests/
  ├── unit/                # Unit tests (no DB)
  └── integration/         # Integration tests (with DB)
```

---

## Common Issues & Fixes

### "ModuleNotFoundError: No module named 'app'"
→ Ensure virtual environment is active and you're running commands from project root.

### "password authentication failed for user 'postgres'"
→ Update `.env` with correct PostgreSQL password.

### "relation already exists" during migration
→ Run `alembic downgrade base` then `alembic upgrade head`.

### Tests fail with connection timeout
→ Ensure PostgreSQL container is running: `docker ps`.

---

## API Endpoints (Milestone 1)

- `GET /health/` - Health check (returns DB connection status)
- `GET /docs` - Interactive API documentation (Swagger UI)
- `GET /redoc` - Alternative API documentation (ReDoc)

---

## Next Milestone Preview

**MILESTONE 2**: Perception (YOLOv8 + Tracking)
- Install: `pip install ultralytics opencv-python`
- New modules: `src/app/cv/detection.py`, `src/app/cv/tracking.py`
- API endpoint: `POST /api/videos/upload`
- Tests: Detection accuracy, tracking consistency
