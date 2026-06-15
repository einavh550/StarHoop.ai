"""Integration test for the Milestone 6 reel composition.

Exercises :func:`compose_reel` against a SQLite database with a seeded M5 reel
and clips. The ffmpeg render and R2 asset access are stubbed so the test needs
no real media, binary or network, while still validating the ``ComposedReel``
lifecycle, asset resolution wiring and the composed-row metadata.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.cv.highlights import audio as audio_mod
from app.cv.highlights import compose as compose_mod
from app.cv.highlights import compose_service as service_mod
from app.cv.highlights import overlays as overlays_mod
from app.cv.highlights.compose_service import ReelNotReadyError, compose_reel
from app.db.base import Base
from app.db.models import (
    Coach,
    ComposedReel,
    HighlightClip,
    HighlightReel,
    Player,
    Team,
    VideoJob,
)


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _seed(db, tmp_path: Path, *, status: str = "completed") -> tuple[VideoJob, HighlightReel, Player]:
    coach = Coach(full_name="Coach", email="coach@test.com")
    db.add(coach)
    db.flush()
    team = Team(coach_id=coach.id, name="Team", season="2025-2026", logo_url=None)
    db.add(team)
    db.flush()
    player = Player(
        team_id=team.id,
        full_name="Colton Large",
        jersey_number=14,
        photo_url="assets/players/team_1/jersey_14/photo.png",
    )
    db.add(player)
    db.flush()
    job = VideoJob(
        team_id=team.id,
        status="completed",
        source_filename="game.mp4",
        storage_path="/uploads/game.mp4",
        total_frames=300,
        processed_frames=300,
    )
    db.add(job)
    db.flush()

    reel = HighlightReel(
        video_job_id=job.id,
        status=status,
        source_mode="annotated",
        scope="player",
        player_id=player.id,
        clip_count=2,
        total_duration_sec=Decimal("8.000"),
    )
    db.add(reel)
    db.flush()

    for index, (event_type, made) in enumerate([("layup_dunk", True), ("shot_attempt", False)]):
        clip_file = tmp_path / f"clip_{index}.mp4"
        clip_file.write_bytes(b"clip")
        db.add(
            HighlightClip(
                reel_id=reel.id,
                video_job_id=job.id,
                event_type=event_type,
                source="action",
                track_id=1,
                mapped_player_id=player.id,
                start_frame=10 * index,
                end_frame=10 * index + 30,
                start_timestamp_sec=Decimal("1.000"),
                end_timestamp_sec=Decimal("3.000"),
                made=made,
                score=0.9,
                confidence=0.9,
                clip_path=str(clip_file),
                clip_filename=clip_file.name,
                order_index=index,
            )
        )
    db.commit()
    return job, reel, player


def _install_stubs(monkeypatch: pytest.MonkeyPatch) -> None:
    # No real R2: music + logo listing return fixed keys, downloads write a file.
    monkeypatch.setattr(audio_mod, "list_music_keys", lambda: ["assets/music/anthem.mp3"])
    monkeypatch.setattr(service_mod, "_resolve_logo_key", lambda: "assets/branding/logo.png")

    def _fake_download(key: str, local_path) -> str:
        path = Path(local_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Logo/photo must be valid images so Pillow can open them.
        if key.endswith((".png", ".jpg", ".jpeg")):
            from PIL import Image

            Image.new("RGBA", (120, 120), (255, 255, 255, 255)).save(path)
        else:
            path.write_bytes(b"music")
        return str(path)

    monkeypatch.setattr(service_mod.r2_storage, "download_file", _fake_download)

    # Stub the ffmpeg render: emit an output file and report a duration.
    def _fake_render(*, output_path, **kwargs) -> float:
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"composed")
        return 11.5

    monkeypatch.setattr(compose_mod, "render_composition", _fake_render)


def test_compose_reel_completes_and_persists(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(service_mod.settings, "compose_export_dir", str(tmp_path / "composed"))
    monkeypatch.setattr(service_mod.settings, "compose_work_dir", str(tmp_path / "work"))
    _install_stubs(monkeypatch)

    db = _make_db()
    job, reel, player = _seed(db, tmp_path)

    composed = compose_reel(db=db, job_id=job.id, reel_id=reel.id, aspect_ratio="16:9")

    assert composed.status == "completed"
    assert composed.aspect_ratio == "16:9"
    assert composed.player_id == player.id
    assert composed.music_track == "assets/music/anthem.mp3"
    assert composed.has_intro is True
    assert float(composed.total_duration_sec) == pytest.approx(11.5)
    assert composed.output_path and Path(composed.output_path).exists()

    rows = db.query(ComposedReel).filter(ComposedReel.reel_id == reel.id).all()
    assert len(rows) == 1
    db.close()


def test_compose_reel_vertical_aspect(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(service_mod.settings, "compose_export_dir", str(tmp_path / "composed"))
    monkeypatch.setattr(service_mod.settings, "compose_work_dir", str(tmp_path / "work"))
    _install_stubs(monkeypatch)

    captured: dict = {}

    def _capture_render(*, output_path, width, height, **kwargs) -> float:
        captured["width"] = width
        captured["height"] = height
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"composed")
        return 9.0

    monkeypatch.setattr(compose_mod, "render_composition", _capture_render)

    db = _make_db()
    job, reel, _ = _seed(db, tmp_path)

    composed = compose_reel(db=db, job_id=job.id, reel_id=reel.id, aspect_ratio="9:16")

    assert composed.aspect_ratio == "9:16"
    # Vertical: the height is the long edge.
    assert captured["height"] > captured["width"]
    db.close()


def test_compose_reel_invalid_aspect_raises(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _install_stubs(monkeypatch)
    db = _make_db()
    job, reel, _ = _seed(db, tmp_path)

    with pytest.raises(service_mod.CompositionRequestError):
        compose_reel(db=db, job_id=job.id, reel_id=reel.id, aspect_ratio="4:3")
    db.close()


def test_compose_reel_requires_completed_source(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _install_stubs(monkeypatch)
    db = _make_db()
    job, reel, _ = _seed(db, tmp_path, status="processing")

    with pytest.raises(ReelNotReadyError):
        compose_reel(db=db, job_id=job.id, reel_id=reel.id)
    db.close()


def test_compose_reel_marks_failed_on_render_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(service_mod.settings, "compose_export_dir", str(tmp_path / "composed"))
    monkeypatch.setattr(service_mod.settings, "compose_work_dir", str(tmp_path / "work"))
    _install_stubs(monkeypatch)

    def _boom(**kwargs) -> float:
        raise compose_mod.CompositionError("ffmpeg blew up")

    monkeypatch.setattr(compose_mod, "render_composition", _boom)

    db = _make_db()
    job, reel, _ = _seed(db, tmp_path)

    with pytest.raises(compose_mod.CompositionError):
        compose_reel(db=db, job_id=job.id, reel_id=reel.id)

    row = db.query(ComposedReel).filter(ComposedReel.reel_id == reel.id).first()
    assert row is not None
    assert row.status == "failed"
    assert row.error_message
    db.close()
