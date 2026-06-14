from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class HighlightClip(Base):
    """A single padded sub-clip that belongs to a :class:`HighlightReel`.

    Each row records the derived event it was cut from (type, source, track and
    optional mapped player), the exact time window extracted, and where the
    rendered clip lives on disk so it can be downloaded individually.
    """

    __tablename__ = "highlight_clips"
    __table_args__ = (
        CheckConstraint(
            "source IN ('action', 'frame')",
            name="ck_highlight_clips_source",
        ),
        CheckConstraint("score >= 0.0", name="ck_highlight_clips_score_non_negative"),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_highlight_clips_confidence_range",
        ),
        CheckConstraint(
            "start_frame >= 0 AND end_frame >= 0 AND end_frame >= start_frame",
            name="ck_highlight_clips_frame_range",
        ),
        CheckConstraint(
            "start_timestamp_sec >= 0.0 AND end_timestamp_sec >= 0.0 AND end_timestamp_sec >= start_timestamp_sec",
            name="ck_highlight_clips_time_range",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    reel_id: Mapped[int] = mapped_column(
        ForeignKey("highlight_reels.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    video_job_id: Mapped[int] = mapped_column(
        ForeignKey("video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    track_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    mapped_player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    start_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    end_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    start_timestamp_sec: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    end_timestamp_sec: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    made: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)
    clip_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    clip_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    reel = relationship("HighlightReel", back_populates="clips")
    mapped_player = relationship("Player")
