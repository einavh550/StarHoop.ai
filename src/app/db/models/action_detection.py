from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ActionDetection(Base):
    __tablename__ = "action_detections"
    __table_args__ = (
        CheckConstraint("action_confidence >= 0.0 AND action_confidence <= 1.0", name="ck_action_detections_confidence_range"),
        CheckConstraint("start_frame >= 0 AND end_frame >= 0 AND end_frame >= start_frame", name="ck_action_detections_frame_range"),
        CheckConstraint(
            "start_timestamp_sec >= 0.0 AND end_timestamp_sec >= 0.0 AND end_timestamp_sec >= start_timestamp_sec",
            name="ck_action_detections_time_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    video_job_id: Mapped[int] = mapped_column(
        ForeignKey("video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    track_id: Mapped[int | None] = mapped_column(nullable=True, index=True)
    action_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    action_confidence: Mapped[float] = mapped_column(nullable=False)
    start_frame: Mapped[int] = mapped_column(nullable=False)
    end_frame: Mapped[int] = mapped_column(nullable=False)
    start_timestamp_sec: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    end_timestamp_sec: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    mapped_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    video_job = relationship("VideoJob", back_populates="action_detections")
    mapped_player = relationship("Player")
