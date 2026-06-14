from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


class HighlightReel(Base):
    """A stitched highlight reel derived from a completed video job.

    Milestone 5 produces a *master* reel (all events for all players) by default.
    When ``scope == 'player'`` the reel is a minimal per-player cut built from the
    same extracted clips, filtered to ``player_id``. The richer per-player editing
    (intro card, overlays, music) is layered on top of this in Milestone 6.
    """

    __tablename__ = "highlight_reels"
    __table_args__ = (
        CheckConstraint(
            "status IN ('processing', 'completed', 'failed')",
            name="ck_highlight_reels_status",
        ),
        CheckConstraint(
            "source_mode IN ('clean', 'annotated')",
            name="ck_highlight_reels_source_mode",
        ),
        CheckConstraint(
            "scope IN ('all', 'player')",
            name="ck_highlight_reels_scope",
        ),
        CheckConstraint("clip_count >= 0", name="ck_highlight_reels_clip_count_non_negative"),
        CheckConstraint(
            "total_duration_sec >= 0.0",
            name="ck_highlight_reels_duration_non_negative",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    video_job_id: Mapped[int] = mapped_column(
        ForeignKey("video_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="processing")
    source_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="clean")
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default="all")
    player_id: Mapped[int | None] = mapped_column(
        ForeignKey("players.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    clip_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_duration_sec: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False, default=Decimal("0.000"))
    output_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    output_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    error_message: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    video_job = relationship("VideoJob", back_populates="highlight_reels")
    player = relationship("Player")
    clips = relationship(
        "HighlightClip",
        back_populates="reel",
        cascade="all, delete-orphan",
        order_by="HighlightClip.order_index",
    )
