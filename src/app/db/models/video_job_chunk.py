from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class VideoJobChunk(Base):
    """One time-segment of a video processed by a single Modal GPU worker.

    A ``VideoJob`` with ``chunks_total > 1`` fans out K workers, each owning
    one ``VideoJobChunk``. The job transitions to ``completed`` only when all
    chunks have sent their ``final_batch``.

    ``track_id_offset`` is pre-computed at spawn time so each chunk's SAM-2
    tracker uses a distinct ID namespace, preventing collisions in
    ``detection_frames.detections_json``.
    """

    __tablename__ = "video_job_chunks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'canceled')",
            name="ck_video_job_chunks_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    track_id_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    modal_call_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )

    video_job = relationship("VideoJob", back_populates="chunks")
