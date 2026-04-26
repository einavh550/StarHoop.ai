"""milestone 2 video jobs and detection frames

Revision ID: 20260307_000002
Revises: 20260224_000001
Create Date: 2026-03-07 00:00:02

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260307_000002"
down_revision: str | None = "20260224_000001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "video_jobs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("source_filename", sa.String(length=255), nullable=False),
        sa.Column("storage_path", sa.String(length=1024), nullable=False),
        sa.Column("tracker_name", sa.String(length=32), nullable=False, server_default=sa.text("'bytetrack'")),
        sa.Column("model_name", sa.String(length=64), nullable=False, server_default=sa.text("'yolov8n'")),
        sa.Column("total_frames", sa.Integer(), nullable=True),
        sa.Column("processed_frames", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_video_jobs_status",
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_video_jobs_team_id", "video_jobs", ["team_id"], unique=False)
    op.create_index("ix_video_jobs_status", "video_jobs", ["status"], unique=False)

    op.create_table(
        "detection_frames",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("video_job_id", sa.BigInteger(), nullable=False),
        sa.Column("frame_number", sa.Integer(), nullable=False),
        sa.Column("timestamp_sec", sa.Numeric(10, 3), nullable=False),
        sa.Column("detections_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["video_job_id"], ["video_jobs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("video_job_id", "frame_number", name="uq_detection_frames_job_frame"),
    )
    op.create_index("ix_detection_frames_video_job_id", "detection_frames", ["video_job_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_detection_frames_video_job_id", table_name="detection_frames")
    op.drop_table("detection_frames")

    op.drop_index("ix_video_jobs_status", table_name="video_jobs")
    op.drop_index("ix_video_jobs_team_id", table_name="video_jobs")
    op.drop_table("video_jobs")
