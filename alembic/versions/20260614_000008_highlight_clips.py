"""Milestone 5: highlight reels and clips for clip extraction & stitching.

Revision ID: 20260614_000008
Revises: 20260613_000007
Create Date: 2026-06-14 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260614_000008"
down_revision = "20260613_000007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "highlight_reels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("video_job_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source_mode", sa.String(length=16), nullable=False),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=True),
        sa.Column("clip_count", sa.Integer(), nullable=False),
        sa.Column("total_duration_sec", sa.Numeric(10, 3), nullable=False),
        sa.Column("output_path", sa.String(length=1024), nullable=True),
        sa.Column("output_filename", sa.String(length=255), nullable=True),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["video_job_id"], ["video_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("status IN ('processing', 'completed', 'failed')", name="ck_highlight_reels_status"),
        sa.CheckConstraint("source_mode IN ('clean', 'annotated')", name="ck_highlight_reels_source_mode"),
        sa.CheckConstraint("scope IN ('all', 'player')", name="ck_highlight_reels_scope"),
        sa.CheckConstraint("clip_count >= 0", name="ck_highlight_reels_clip_count_non_negative"),
        sa.CheckConstraint("total_duration_sec >= 0.0", name="ck_highlight_reels_duration_non_negative"),
    )
    op.create_index("ix_highlight_reels_video_job_id", "highlight_reels", ["video_job_id"])
    op.create_index("ix_highlight_reels_player_id", "highlight_reels", ["player_id"])

    op.create_table(
        "highlight_clips",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("reel_id", sa.Integer(), nullable=False),
        sa.Column("video_job_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=True),
        sa.Column("mapped_player_id", sa.Integer(), nullable=True),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("start_timestamp_sec", sa.Numeric(10, 3), nullable=False),
        sa.Column("end_timestamp_sec", sa.Numeric(10, 3), nullable=False),
        sa.Column("made", sa.Boolean(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("clip_path", sa.String(length=1024), nullable=True),
        sa.Column("clip_filename", sa.String(length=255), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["reel_id"], ["highlight_reels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["video_job_id"], ["video_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["mapped_player_id"], ["players.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("source IN ('action', 'frame')", name="ck_highlight_clips_source"),
        sa.CheckConstraint("score >= 0.0", name="ck_highlight_clips_score_non_negative"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_highlight_clips_confidence_range"),
        sa.CheckConstraint(
            "start_frame >= 0 AND end_frame >= 0 AND end_frame >= start_frame",
            name="ck_highlight_clips_frame_range",
        ),
        sa.CheckConstraint(
            "start_timestamp_sec >= 0.0 AND end_timestamp_sec >= 0.0 AND end_timestamp_sec >= start_timestamp_sec",
            name="ck_highlight_clips_time_range",
        ),
    )
    op.create_index("ix_highlight_clips_reel_id", "highlight_clips", ["reel_id"])
    op.create_index("ix_highlight_clips_video_job_id", "highlight_clips", ["video_job_id"])
    op.create_index("ix_highlight_clips_event_type", "highlight_clips", ["event_type"])
    op.create_index("ix_highlight_clips_track_id", "highlight_clips", ["track_id"])
    op.create_index("ix_highlight_clips_mapped_player_id", "highlight_clips", ["mapped_player_id"])


def downgrade() -> None:
    op.drop_index("ix_highlight_clips_mapped_player_id", table_name="highlight_clips")
    op.drop_index("ix_highlight_clips_track_id", table_name="highlight_clips")
    op.drop_index("ix_highlight_clips_event_type", table_name="highlight_clips")
    op.drop_index("ix_highlight_clips_video_job_id", table_name="highlight_clips")
    op.drop_index("ix_highlight_clips_reel_id", table_name="highlight_clips")
    op.drop_table("highlight_clips")

    op.drop_index("ix_highlight_reels_player_id", table_name="highlight_reels")
    op.drop_index("ix_highlight_reels_video_job_id", table_name="highlight_reels")
    op.drop_table("highlight_reels")
