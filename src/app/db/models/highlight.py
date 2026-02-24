from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Highlight(Base):
    __tablename__ = "highlights"
    __table_args__ = (
        CheckConstraint("event_timestamp_sec >= 0", name="ck_highlights_event_timestamp_non_negative"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False, index=True)
    video_url: Mapped[str] = mapped_column(String(1024), nullable=False)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    event_timestamp_sec: Mapped[Decimal] = mapped_column(Numeric(10, 3), nullable=False)
    source_video_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)

    player = relationship("Player", back_populates="highlights")
