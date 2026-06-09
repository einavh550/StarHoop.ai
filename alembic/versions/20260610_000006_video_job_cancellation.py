"""Add job cancellation fields/state for video jobs.

Revision ID: 20260610_000006
Revises: 20260607_000005
Create Date: 2026-06-10 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260610_000006"
down_revision = "20260607_000005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "video_jobs",
        sa.Column("modal_call_id", sa.String(length=128), nullable=True),
    )

    op.drop_constraint("ck_video_jobs_status", "video_jobs", type_="check")
    op.create_check_constraint(
        "ck_video_jobs_status",
        "video_jobs",
        "status IN ('pending', 'processing', 'completed', 'failed', 'canceled')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_video_jobs_status", "video_jobs", type_="check")
    op.create_check_constraint(
        "ck_video_jobs_status",
        "video_jobs",
        "status IN ('pending', 'processing', 'completed', 'failed')",
    )

    op.drop_column("video_jobs", "modal_call_id")
