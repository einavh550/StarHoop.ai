from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class DetectionFrame(Base):
    __tablename__ = "detection_frames"
    __table_args__ = (
        UniqueConstraint("video_job_id", "frame_number", name="uq_detection_frames_job_frame"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    video_job_id: Mapped[int] = mapped_column(
        ForeignKey("video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    frame_number: Mapped[int] = mapped_column(nullable=False)
    timestamp_sec: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    detections_json: Mapped[list[dict]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    video_job = relationship("VideoJob", back_populates="detection_frames")
