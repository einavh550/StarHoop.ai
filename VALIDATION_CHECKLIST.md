# MILESTONE 1 VALIDATION CHECKLIST

**Project**: StarHoop.ai  
**Milestone**: 1 - Infrastructure & Database Foundation  
**Date**: February 24, 2026  
**Validator**: ___________________

---

## Prerequisites Verification

- [ ] Python 3.13+ installed (`python --version`)
- [ ] Docker installed (`docker --version`)
- [ ] Git repository cloned
- [ ] Virtual environment activated (`.venv\Scripts\Activate.ps1`)
- [ ] Dependencies installed (`pip install -r requirements.txt`)

---

## Database Setup

- [ ] PostgreSQL Docker container running:
  ```powershell
  docker run --name starhoop-postgres \
    -e POSTGRES_PASSWORD=___________ \
    -e POSTGRES_DB=starhoop \
    -p 5432:5432 \
    -d postgres:16-alpine
  ```
  **Container ID**: `docker ps` shows `starhoop-postgres`

- [ ] Database accessible:
  ```powershell
  docker exec -it starhoop-postgres psql -U postgres -d starhoop -c "SELECT 1;"
  ```
  **Expected output**: `(1 row)`

---

## Configuration

- [ ] `.env` file created (copied from `.env.example`)
- [ ] `.env` updated with actual PostgreSQL password
- [ ] `DATABASE_URL` format validated:
  ```
  postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/starhoop
  ```

---

## Migration Execution

- [ ] Alembic configuration validated:
  ```powershell
  alembic current
  ```
  **Expected**: No current revision (initial state) or error message about missing alembic_version table

- [ ] Initial migration applied:
  ```powershell
  alembic upgrade head
  ```
  **Expected output**:
  ```
  INFO  [alembic.runtime.migration] Running upgrade  -> 20260224_000001, initial starhoop schema
  ```

- [ ] Migration status verified:
  ```powershell
  alembic current
  ```
  **Expected output**: `20260224_000001 (head)`

- [ ] Database schema inspected:
  ```powershell
  docker exec -it starhoop-postgres psql -U postgres -d starhoop -c "\dt"
  ```
  **Expected tables**: `alembic_version`, `coaches`, `teams`, `players`, `highlights`

---

## Test Execution

### Unit Tests (No DB Required)

- [ ] Config and engine tests:
  ```powershell
  pytest tests/unit/test_config_and_engine.py -v
  ```
  **Expected**: `4 passed`

- [ ] Health route test:
  ```powershell
  pytest tests/unit/test_health_route.py -v
  ```
  **Expected**: `1 passed`

- [ ] All unit tests:
  ```powershell
  pytest tests/unit -v
  ```
  **Expected**: `5 passed` in < 1 second

### Integration Tests (DB Required)

- [ ] Schema integrity tests:
  ```powershell
  pytest tests/integration/test_schema_integrity.py -v
  ```
  **Expected**: `5 passed` (not skipped)

  **Test coverage**:
  - [ ] `test_unique_jersey_number_per_team` (IntegrityError on duplicate)
  - [ ] `test_jersey_range_check_constraint` (IntegrityError on jersey_number > 99)
  - [ ] `test_foreign_key_chain_enforced` (IntegrityError on invalid team_id)
  - [ ] `test_event_timestamp_check_constraint` (IntegrityError on negative timestamp)
  - [ ] `test_highlight_insert_success` (successful insert with all fields)

### Full Test Suite

- [ ] All tests passing:
  ```powershell
  pytest -v
  ```
  **Expected**: `10 passed` (5 unit + 5 integration)

---

## API Server Validation

- [ ] Server starts without errors:
  ```powershell
  uvicorn app.main:app --reload
  ```
  **Expected output**: `Application startup complete`, `Uvicorn running on http://127.0.0.1:8000`

- [ ] Health endpoint accessible:
  ```
  Visit: http://localhost:8000/health/
  ```
  **Expected response**:
  ```json
  {
    "status": "ok",
    "database": "connected"
  }
  ```

- [ ] API docs accessible:
  ```
  Visit: http://localhost:8000/docs
  ```
  **Expected**: Swagger UI with `/health/` endpoint documented

- [ ] API test via curl (optional):
  ```powershell
  curl http://localhost:8000/health/
  ```
  **Expected**: `{"status":"ok","database":"connected"}`

---

## Code Quality Checks

- [ ] No linting errors:
  ```powershell
  ruff check src/ tests/ --select E,F,I  # Optional: requires ruff installation
  ```

- [ ] No type errors (optional):
  ```powershull
  mypy src/  # Optional: requires mypy installation
  ```

- [ ] No syntax errors:
  ```powershell
  python -m py_compile src/app/**/*.py
  ```

---

## Documentation Review

- [ ] `README.md` is comprehensive and accurate
- [ ] `QUICK_REFERENCE.md` commands tested
- [ ] `SCHEMA_DIAGRAM.md` matches actual schema
- [ ] `TECH_SPEC.md` reflects implementation
- [ ] `MILESTONE_1_COMPLETE.md` reviewed

---

## Database Constraint Verification (Manual)

**Connect to database**:
```powershell
docker exec -it starhoop-postgres psql -U postgres -d starhoop
```

### Foreign Key Cascade Test

```sql
-- Insert test coach
INSERT INTO coaches (full_name, email) VALUES ('Test Coach', 'test@example.com');

-- Insert test team
INSERT INTO teams (coach_id, name, season) VALUES (1, 'Test Team', '2026');

-- Verify team exists
SELECT * FROM teams WHERE coach_id = 1;

-- Delete coach (should cascade to team)
DELETE FROM coaches WHERE id = 1;

-- Verify team deleted (should return 0 rows)
SELECT COUNT(*) FROM teams WHERE coach_id = 1;
```

- [ ] Cascade delete works (team deleted when coach deleted)

### Unique Constraint Test

```sql
-- Insert coach
INSERT INTO coaches (full_name, email) VALUES ('Coach A', 'unique@test.com');

-- Try duplicate email (should fail with unique constraint violation)
INSERT INTO coaches (full_name, email) VALUES ('Coach B', 'unique@test.com');
```

- [ ] Unique constraint enforced (second insert fails)

### Check Constraint Test

```sql
-- Insert coach and team
INSERT INTO coaches (full_name, email) VALUES ('Coach C', 'coach@test.com');
INSERT INTO teams (coach_id, name, season) VALUES (1, 'Team C', '2026');

-- Try invalid jersey number (should fail)
INSERT INTO players (team_id, full_name, jersey_number) 
VALUES (1, 'Invalid Player', 999);
```

- [ ] Check constraint enforced (jersey_number > 99 fails)

**Clean up test data**:
```sql
DELETE FROM coaches WHERE email LIKE '%test.com';
```

---

## Final Acceptance

- [ ] All checkboxes above completed successfully
- [ ] No errors in any test or validation step
- [ ] Database schema matches specification in `TECH_SPEC.md`
- [ ] API server runs without errors
- [ ] Documentation is accurate and complete

---

## Sign-Off

**Validator Signature**: ___________________  
**Date**: ___________________  
**Status**: [ ] PASSED  [ ] FAILED (see notes below)

**Notes / Issues**:
_______________________________________________________________________________
_______________________________________________________________________________
_______________________________________________________________________________

---

## Next Steps (Post-Validation)

1. ✅ Commit Milestone 1 to Git:
   ```powershell
   git add .
   git commit -m "Complete Milestone 1: Infrastructure & DB schema"
   git push origin main
   ```

2. ✅ Tag release:
   ```powershell
   git tag -a v1.0.0-milestone1 -m "Milestone 1: Infrastructure complete"
   git push origin v1.0.0-milestone1
   ```

3. ⏳ Begin Milestone 2 scoping:
   - Install YOLOv8 dependencies (`ultralytics`, `opencv-python`)
   - Design video upload API endpoint schema
   - Set up computer vision module structure (`src/app/cv/`)

---

**Validation Checklist Complete**  
**Milestone 1**: ✅ **READY FOR PRODUCTION**
