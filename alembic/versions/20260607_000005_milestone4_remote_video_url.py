"""Milestone 4: store the remote (R2) video URL on video jobs.

Adds ``video_jobs.remote_video_url`` so the orchestration flow can record the
Cloudflare R2 object the Modal GPU worker downloads for processing.

Revision ID: 20260607_000005
Revises: 20260427_000004
Create Date: 2026-06-07 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260607_000005'
down_revision = '20260427_000004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        'video_jobs',
        sa.Column('remote_video_url', sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('video_jobs', 'remote_video_url')
