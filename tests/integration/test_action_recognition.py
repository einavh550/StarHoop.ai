from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.cv.actions import ActionRecognizer
from app.db.base import Base
from app.db.models import Coach, DetectionFrame, JerseyDetection, Player, Team, VideoJob


def test_action_recognition_end_to_end() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    coach = Coach(full_name="Coach", email="coach@test.com")
    db.add(coach)
    db.flush()

    team = Team(coach_id=coach.id, name="Team", season="2025-2026", logo_url=None)
    db.add(team)
    db.flush()

    player = Player(team_id=team.id, full_name="Player 9", jersey_number=9)
    db.add(player)
    db.flush()

    job = VideoJob(
        team_id=team.id,
        status="completed",
        source_filename="video.mp4",
        storage_path="/uploads/video.mp4",
        total_frames=30,
        processed_frames=30,
    )
    db.add(job)
    db.flush()

    db.add(
        JerseyDetection(
            video_job_id=job.id,
            track_id=1,
            detected_jersey_number=9,
            jersey_confidence=0.91,
            frame_count=7,
            confidence_mean=0.90,
            confidence_max=0.93,
            mapped_player_id=player.id,
        )
    )

    # Synthetic up-then-down movement sequence for one track.
    centers = [240, 232, 222, 208, 215, 226, 239]
    for idx, center in enumerate(centers):
        y1 = float(center - 40)
        y2 = float(center + 40)
        db.add(
            DetectionFrame(
                video_job_id=job.id,
                frame_number=idx,
                timestamp_sec=Decimal(f"{idx * 0.033:.3f}"),
                detections_json=[
                    {
                        "class_id": 0,
                        "class_name": "person",
                        "confidence": 0.92,
                        "track_id": 1,
                        "bbox": {"x1": 100.0, "y1": y1, "x2": 160.0, "y2": y2},
                    }
                ],
            )
        )

    db.commit()

    candidates = ActionRecognizer.detect_actions_from_video(db, job.id)
    persisted = ActionRecognizer.persist_action_detections(db, job.id, candidates)

    assert len(candidates) == 1
    assert candidates[0].action_type == "shot_attempt"
    assert candidates[0].mapped_player_id == player.id
    assert len(persisted) == 1

    db.close()
