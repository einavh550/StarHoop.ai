from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class JerseyDetection(Base):
    """
    Aggregated jersey detections from video processing.
    
    Maps detected jersey numbers (via OCR in M3P1) to Player records.
    Provides confidence metrics across frames for each track_id.
    """
    __tablename__ = "jersey_detections"
    __table_args__ = (
        UniqueConstraint("video_job_id", "track_id", name="uq_jersey_detections_job_track"),
        CheckConstraint(
            "detected_jersey_number >= 0 AND detected_jersey_number <= 99",
            name="ck_jersey_detections_jersey_range"
        ),
        CheckConstraint(
            "jersey_confidence >= 0.0 AND jersey_confidence <= 1.0",
            name="ck_jersey_detections_confidence_range"
        ),
        CheckConstraint(
            "confidence_mean >= 0.0 AND confidence_mean <= 1.0",
            name="ck_jersey_detections_mean_confidence_range"
        ),
        CheckConstraint(
            "confidence_max >= 0.0 AND confidence_max <= 1.0",
            name="ck_jersey_detections_max_confidence_range"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    video_job_id: Mapped[int] = mapped_column(
        ForeignKey("video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    track_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    detected_jersey_number: Mapped[int] = mapped_column(Integer, nullable=False)
    jersey_confidence: Mapped[float] = mapped_column(nullable=False)
    frame_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confidence_mean: Mapped[float] = mapped_column(nullable=False)
    confidence_max: Mapped[float] = mapped_column(nullable=False)
    mapped_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    video_job = relationship("VideoJob", back_populates="jersey_detections")
    mapped_player = relationship("Player", foreign_keys=[mapped_player_id])
