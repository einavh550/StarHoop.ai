"""Integration test for the Milestone 5 highlight pipeline.

Exercises the real event derivation, ranking and persistence against a SQLite
database. The ffmpeg-backed media steps are stubbed so the test needs no real
video file or ffmpeg binary, while still validating clip/reel rows, the master
vs. per-player scope, and made-shot flagging.
"""

from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.cv.highlights import service as service_mod
from app.cv.highlights.service import EmptyReelError, PlayerNotFoundError, generate_highlights
from app.db.base import Base
from app.db.models import (
    ActionDetection,
    Coach,
    DetectionFrame,
    HighlightClip,
    HighlightReel,
    JerseyDetection,
    Player,
    Team,
    VideoJob,
)


def _frame(job_id: int, frame_number: int, timestamp: float, detections: list[dict]) -> DetectionFrame:
    return DetectionFrame(
        video_job_id=job_id,
        frame_number=frame_number,
        timestamp_sec=Decimal(f"{timestamp:.3f}"),
        detections_json=detections,
    )


def _seed(db) -> tuple[VideoJob, Player, Player]:
    coach = Coach(full_name="Coach", email="coach@test.com")
    db.add(coach)
    db.flush()
    team = Team(coach_id=coach.id, name="Team", season="2025-2026", logo_url=None)
    db.add(team)
    db.flush()
    p7 = Player(team_id=team.id, full_name="Player 7", jersey_number=7)
    p9 = Player(team_id=team.id, full_name="Player 9", jersey_number=9)
    db.add_all([p7, p9])
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

    # track 1 -> player 7, track 2 -> player 9
    db.add_all([
        JerseyDetection(
            video_job_id=job.id, track_id=1, detected_jersey_number=7, jersey_confidence=0.9,
            frame_count=5, confidence_mean=0.9, confidence_max=0.95, mapped_player_id=p7.id,
        ),
        JerseyDetection(
            video_job_id=job.id, track_id=2, detected_jersey_number=9, jersey_confidence=0.9,
            frame_count=5, confidence_mean=0.9, confidence_max=0.95, mapped_player_id=p9.id,
        ),
    ])

    # A shot_attempt by player 7 (track 1), ending at 2.0s.
    db.add(ActionDetection(
        video_job_id=job.id, track_id=1, action_type="shot_attempt", action_confidence=0.9,
        start_frame=40, end_frame=60, start_timestamp_sec=Decimal("1.500"),
        end_timestamp_sec=Decimal("2.000"), mapped_player_id=p7.id,
    ))

    # Frame-class events: a layup-dunk by player 9 (track 2) and a possession.
    db.add_all([
        _frame(job.id, 90, 3.0, [{"class_name": "player-layup-dunk", "track_id": 2, "confidence": 0.8}]),
        _frame(job.id, 93, 3.1, [{"class_name": "player-layup-dunk", "track_id": 2, "confidence": 0.85}]),
        _frame(job.id, 120, 4.0, [{"class_name": "player-in-possession", "track_id": 1, "confidence": 0.7}]),
        _frame(job.id, 123, 4.1, [{"class_name": "player-in-possession", "track_id": 1, "confidence": 0.7}]),
        # Ball-in-basket shortly after the shot_attempt ends -> shot is "made".
        _frame(job.id, 70, 2.4, [{"class_name": "ball-in-basket", "track_id": None, "confidence": 0.9}]),
    ])
    db.commit()
    return job, p7, p9


def _install_media_stubs(monkeypatch: pytest.MonkeyPatch, source: Path) -> None:
    monkeypatch.setattr(service_mod, "resolve_source", lambda db, job, source_mode: source)
    monkeypatch.setattr(service_mod, "probe_duration", lambda path: 600.0)

    def _fake_extract(source_path, *, start_sec, end_sec, pad_pre_sec, pad_post_sec, output_path, source_duration_sec=None):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"clip")
        return (end_sec + pad_post_sec) - max(0.0, start_sec - pad_pre_sec)

    def _fake_stitch(clip_paths, output_path):
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        Path(output_path).write_bytes(b"reel")

    monkeypatch.setattr(service_mod, "extract_clip", _fake_extract)
    monkeypatch.setattr(service_mod, "stitch_clips", _fake_stitch)


def _make_db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_master_reel_includes_all_players(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(service_mod.settings, "highlight_export_dir", str(tmp_path / "highlights"))
    source = tmp_path / "game.mp4"
    source.write_bytes(b"video")
    _install_media_stubs(monkeypatch, source)

    db = _make_db()
    job, p7, p9 = _seed(db)

    reel = generate_highlights(db, job.id, source_mode="clean")

    assert reel.status == "completed"
    assert reel.scope == "all"
    assert reel.player_id is None
    assert reel.clip_count >= 3  # shot_attempt + layup_dunk + possession
    assert reel.output_path and Path(reel.output_path).exists()

    clips = db.query(HighlightClip).filter(HighlightClip.reel_id == reel.id).all()
    event_types = {c.event_type for c in clips}
    assert {"shot_attempt", "layup_dunk", "possession"}.issubset(event_types)
    # Made-shot flag propagated to the shot clip.
    shot_clip = next(c for c in clips if c.event_type == "shot_attempt")
    assert shot_clip.made is True
    # order_index is dense and starts at 0.
    assert sorted(c.order_index for c in clips) == list(range(len(clips)))
    db.close()


def test_player_reel_filters_to_single_player(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(service_mod.settings, "highlight_export_dir", str(tmp_path / "highlights"))
    source = tmp_path / "game.mp4"
    source.write_bytes(b"video")
    _install_media_stubs(monkeypatch, source)

    db = _make_db()
    job, p7, p9 = _seed(db)

    reel = generate_highlights(db, job.id, source_mode="clean", player_id=p9.id)

    assert reel.scope == "player"
    assert reel.player_id == p9.id
    clips = db.query(HighlightClip).filter(HighlightClip.reel_id == reel.id).all()
    assert clips, "expected at least one clip for player 9"
    assert all(c.mapped_player_id == p9.id for c in clips)
    assert {c.event_type for c in clips} == {"layup_dunk"}
    db.close()


def test_player_reel_empty_raises(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(service_mod.settings, "highlight_export_dir", str(tmp_path / "highlights"))
    source = tmp_path / "game.mp4"
    source.write_bytes(b"video")
    _install_media_stubs(monkeypatch, source)

    db = _make_db()
    job, p7, p9 = _seed(db)

    # Player exists on the team but a player with no mapped events -> empty reel.
    lonely = Player(team_id=job.team_id, full_name="Bench", jersey_number=23)
    db.add(lonely)
    db.commit()

    with pytest.raises(EmptyReelError):
        generate_highlights(db, job.id, source_mode="clean", player_id=lonely.id)
    db.close()


def test_unknown_player_raises(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(service_mod.settings, "highlight_export_dir", str(tmp_path / "highlights"))
    db = _make_db()
    job, p7, p9 = _seed(db)

    with pytest.raises(PlayerNotFoundError):
        generate_highlights(db, job.id, source_mode="clean", player_id=999999)
    db.close()


def test_reel_marked_failed_on_media_error(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(service_mod.settings, "highlight_export_dir", str(tmp_path / "highlights"))
    source = tmp_path / "game.mp4"
    source.write_bytes(b"video")
    monkeypatch.setattr(service_mod, "resolve_source", lambda db, job, source_mode: source)
    monkeypatch.setattr(service_mod, "probe_duration", lambda path: 600.0)

    def _boom(*args, **kwargs):
        raise RuntimeError("ffmpeg exploded")

    monkeypatch.setattr(service_mod, "extract_clip", _boom)

    db = _make_db()
    job, p7, p9 = _seed(db)

    with pytest.raises(RuntimeError, match="ffmpeg exploded"):
        generate_highlights(db, job.id, source_mode="clean")

    reel = db.query(HighlightReel).filter(HighlightReel.video_job_id == job.id).first()
    assert reel is not None
    assert reel.status == "failed"
    assert reel.error_message and "ffmpeg exploded" in reel.error_message
    db.close()
