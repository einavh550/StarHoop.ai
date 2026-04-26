from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

import app.api.routes.videos as videos_routes
from app.main import app
from app.db.models.team import Team
from app.db.models.video_job import VideoJob
from app.db.session import get_db


class _FakeDB:
    def __init__(self, team_exists: bool = True) -> None:
        self.team_exists = team_exists
        self.jobs: dict[int, VideoJob] = {}
        self.next_job_id = 1

    def get(self, model, object_id):
        if model is Team:
            if self.team_exists and object_id == 1:
                return Team(id=1, coach_id=1, name="Star Hoopers", season="2025-2026")
            return None

        if model is VideoJob:
            return self.jobs.get(object_id)

        return None

    def add(self, obj):
        if isinstance(obj, VideoJob):
            obj.id = self.next_job_id
            self.next_job_id += 1
            self.jobs[obj.id] = obj

    def commit(self):
        return None

    def refresh(self, _obj):
        return None


def _override_db(fake_db: _FakeDB):
    def _fake_get_db():
        yield fake_db

    return _fake_get_db


async def _fake_save_upload_file(*_args, **_kwargs):
    return "game.mp4", "C:/tmp/game.mp4"


def _fake_process_video_job(_job_id: int):
    return None


def test_upload_video_returns_job_id(monkeypatch) -> None:
    fake_db = _FakeDB(team_exists=True)
    monkeypatch.setattr(videos_routes, "save_upload_file", _fake_save_upload_file)
    monkeypatch.setattr(videos_routes, "process_video_job", _fake_process_video_job)

    app.dependency_overrides[get_db] = _override_db(fake_db)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/videos/upload",
                data={"team_id": "1"},
                files={"file": ("game.mp4", b"video-bytes", "video/mp4")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "pending"
    assert payload["job_id"] == 1


def test_upload_video_returns_404_when_team_missing(monkeypatch) -> None:
    fake_db = _FakeDB(team_exists=False)
    monkeypatch.setattr(videos_routes, "save_upload_file", _fake_save_upload_file)
    monkeypatch.setattr(videos_routes, "process_video_job", _fake_process_video_job)

    app.dependency_overrides[get_db] = _override_db(fake_db)
    try:
        with TestClient(app) as client:
            response = client.post(
                "/api/videos/upload",
                data={"team_id": "1"},
                files={"file": ("game.mp4", b"video-bytes", "video/mp4")},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404


def test_get_video_job_status_returns_payload() -> None:
    created_at = datetime(2026, 4, 26, 12, 0, 0, tzinfo=timezone.utc)
    updated_at = created_at + timedelta(seconds=30)

    fake_db = _FakeDB(team_exists=True)
    fake_db.jobs[42] = VideoJob(
        id=42,
        team_id=1,
        status="completed",
        source_filename="game.mp4",
        storage_path="C:/tmp/game.mp4",
        tracker_name="bytetrack",
        model_name="yolov8n.pt",
        total_frames=180,
        processed_frames=90,
        error_message=None,
        created_at=created_at,
        updated_at=updated_at,
    )

    app.dependency_overrides[get_db] = _override_db(fake_db)
    try:
        with TestClient(app) as client:
            response = client.get("/api/videos/42")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == 42
    assert payload["status"] == "completed"
    assert payload["progress_percent"] == 50.0
    assert payload["processing_duration_sec"] == 30.0
    assert payload["throughput_fps"] == 3.0
