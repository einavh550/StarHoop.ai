"""Milestone 6: composed reels for professional personalized reel composition.

Revision ID: 20260615_000009
Revises: 20260614_000008
Create Date: 2026-06-15 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260615_000009"
down_revision = "20260614_000008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "composed_reels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reel_id", sa.Integer(), nullable=False),
        sa.Column("video_job_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("aspect_ratio", sa.String(length=8), nullable=False),
        sa.Column("music_track", sa.String(length=1024), nullable=True),
        sa.Column("has_intro", sa.Boolean(), nullable=False),
        sa.Column("has_stats", sa.Boolean(), nullable=False),
        sa.Column("has_watermark", sa.Boolean(), nullable=False),
        sa.Column("total_duration_sec", sa.Numeric(10, 3), nullable=False),
        sa.Column("output_path", sa.String(length=1024), nullable=True),
        sa.Column("output_filename", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["reel_id"], ["highlight_reels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_job_id"], ["video_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('processing', 'completed', 'failed')", name="ck_composed_reels_status"),
        sa.CheckConstraint("aspect_ratio IN ('16:9', '9:16')", name="ck_composed_reels_aspect_ratio"),
        sa.CheckConstraint("total_duration_sec >= 0.0", name="ck_composed_reels_duration_non_negative"),
    )
    op.create_index("ix_composed_reels_reel_id", "composed_reels", ["reel_id"])
    op.create_index("ix_composed_reels_video_job_id", "composed_reels", ["video_job_id"])
    op.create_index("ix_composed_reels_player_id", "composed_reels", ["player_id"])


def downgrade() -> None:
    op.drop_index("ix_composed_reels_player_id", table_name="composed_reels")
    op.drop_index("ix_composed_reels_video_job_id", table_name="composed_reels")
    op.drop_index("ix_composed_reels_reel_id", table_name="composed_reels")
    op.drop_table("composed_reels")
