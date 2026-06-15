from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class ComposedReel(Base):
    """A polished, share-ready reel composed from an M5 :class:`HighlightReel`.

    Milestone 6 layers presentation quality on top of the raw M5 output: an
    intro/title card, per-clip lower-thirds, a brand watermark, timed fade
    transitions and a music bed (with the original game audio ducked beneath it).
    Each composition is a new row so styling history is preserved; the source M5
    reel is referenced via ``reel_id``.
    """

    __tablename__ = "composed_reels"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_composed_reels_status",
        ),
        CheckConstraint(
            "aspect_ratio IN ('16:9', '9:16')",
            name="ck_composed_reels_aspect_ratio",
        ),
        CheckConstraint(
            "total_duration_sec >= 0.0",
            name="ck_composed_reels_duration_non_negative",
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
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False, default="16:9")
    music_track: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    has_intro: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_stats: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    has_watermark: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    total_duration_sec: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False, default=Decimal("0.000"))
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    reel = relationship("HighlightReel")
    video_job = relationship("VideoJob")
    player = relationship("Player")
