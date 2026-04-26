from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import app.api.routes.videos as videos_routes
from app.main import app
from app.db.models.coach import Coach
from app.db.models.team import Team
from app.db.models.video_job import VideoJob
from app.db.session import get_db


def test_upload_creates_video_job_and_status_endpoint_works(integration_engine, monkeypatch, tmp_path: Path) -> None:
    testing_session_local = sessionmaker(bind=integration_engine, autoflush=False, autocommit=False, future=True)

    setup_session = testing_session_local()
    coach = Coach(full_name="Integration Coach", email=f"coach-{uuid4().hex}@example.com")
    setup_session.add(coach)
    setup_session.flush()

    team = Team(coach_id=coach.id, name="Integration Team", season="2025-2026")
    setup_session.add(team)
    setup_session.commit()
    team_id = team.id
    coach_id = coach.id
    setup_session.close()

    def _override_get_db():
        db = testing_session_local()
        try:
            yield db
        finally:
            db.close()

    async def _fake_save_upload_file(upload_file, storage_dir, max_size_mb, allowed_extensions):
        output_dir = tmp_path
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{uuid4().hex}_integration.mp4"
        output_path.write_bytes(b"integration-video-bytes")
        await upload_file.close()
        return "integration.mp4", str(output_path)

    def _fake_process_video_job(job_id: int):
        db = testing_session_local()
        try:
            job = db.get(VideoJob, job_id)
            if job is not None:
                job.status = "completed"
                job.processed_frames = 1
                db.commit()
        finally:
            db.close()

    monkeypatch.setattr(videos_routes, "save_upload_file", _fake_save_upload_file)
    monkeypatch.setattr(videos_routes, "process_video_job", _fake_process_video_job)

    app.dependency_overrides[get_db] = _override_get_db

    try:
        with TestClient(app) as client:
            upload_response = client.post(
                "/api/videos/upload",
                data={"team_id": str(team_id)},
                files={"file": ("integration.mp4", b"video-data", "video/mp4")},
            )
            assert upload_response.status_code == 202

            job_id = upload_response.json()["job_id"]
            status_response = client.get(f"/api/videos/{job_id}")
            assert status_response.status_code == 200

            payload = status_response.json()
            assert payload["job_id"] == job_id
            assert payload["team_id"] == team_id
            assert payload["status"] in {"pending", "processing", "completed"}
    finally:
        app.dependency_overrides.clear()

        cleanup_session = testing_session_local()
        try:
            inserted_coach = cleanup_session.get(Coach, coach_id)
            if inserted_coach is not None:
                cleanup_session.delete(inserted_coach)
                cleanup_session.commit()
        finally:
            cleanup_session.close()
