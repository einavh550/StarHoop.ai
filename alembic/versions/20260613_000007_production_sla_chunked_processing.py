"""Add chunked parallel processing tables and columns.

Revision ID: 20260613_000007
Revises: 20260610_000006
Create Date: 2026-06-13 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260613_000007"
down_revision = "20260610_000006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add chunked-processing tracking columns to video_jobs.
    op.add_column(
        "video_jobs",
        sa.Column("chunks_total", sa.Integer(), nullable=True),
    )
    op.add_column(
        "video_jobs",
        sa.Column("chunks_done", sa.Integer(), nullable=False, server_default="0"),
    )

    # New table: one row per time-segment worker for a chunked job.
    op.create_table(
        "video_job_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "job_id",
            sa.Integer(),
            sa.ForeignKey("video_jobs.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("start_frame", sa.Integer(), nullable=False),
        sa.Column("end_frame", sa.Integer(), nullable=False),
        sa.Column("track_id_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("modal_call_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed', 'canceled')",
            name="ck_video_job_chunks_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("video_job_chunks")
    op.drop_column("video_jobs", "chunks_done")
    op.drop_column("video_jobs", "chunks_total")
