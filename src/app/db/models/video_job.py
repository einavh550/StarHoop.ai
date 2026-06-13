from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class VideoJob(Base):
    __tablename__ = "video_jobs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'canceled')",
            name="ck_video_jobs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    remote_video_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    modal_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    tracker_name: Mapped[str] = mapped_column(String(32), nullable=False, default="bytetrack")
    model_name: Mapped[str] = mapped_column(String(64), nullable=False, default="yolov8n")
    total_frames: Mapped[int | None] = mapped_column(Integer, nullable=True)
    processed_frames: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Chunked parallel processing: set at spawn time. chunks_done is incremented
    # by each chunk's final_batch webhook; job reaches completed when equal.
    chunks_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunks_done: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    team = relationship("Team", back_populates="video_jobs")
    detection_frames = relationship("DetectionFrame", back_populates="video_job", cascade="all, delete-orphan")
    jersey_detections = relationship("JerseyDetection", back_populates="video_job", cascade="all, delete-orphan")
    action_detections = relationship("ActionDetection", back_populates="video_job", cascade="all, delete-orphan")
    chunks = relationship("VideoJobChunk", back_populates="video_job", cascade="all, delete-orphan")
