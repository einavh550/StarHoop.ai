"""Milestone 4 MVP: Action detections table for spatio-temporal events.

Revision ID: 20260427_000004
Revises: 20260427_000003
Create Date: 2026-04-27 00:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260427_000004'
down_revision = '20260427_000003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'action_detections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('video_job_id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=True),
        sa.Column('action_type', sa.String(length=60), nullable=False),
        sa.Column('action_confidence', sa.Float(), nullable=False),
        sa.Column('start_frame', sa.Integer(), nullable=False),
        sa.Column('end_frame', sa.Integer(), nullable=False),
        sa.Column('start_timestamp_sec', sa.Numeric(10, 3), nullable=False),
        sa.Column('end_timestamp_sec', sa.Numeric(10, 3), nullable=False),
        sa.Column('mapped_player_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['video_job_id'], ['video_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mapped_player_id'], ['players.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.CheckConstraint('action_confidence >= 0.0 AND action_confidence <= 1.0',
                          name='ck_action_detections_confidence_range'),
        sa.CheckConstraint('start_frame >= 0 AND end_frame >= 0 AND end_frame >= start_frame',
                          name='ck_action_detections_frame_range'),
        sa.CheckConstraint('start_timestamp_sec >= 0.0 AND end_timestamp_sec >= 0.0 AND end_timestamp_sec >= start_timestamp_sec',
                          name='ck_action_detections_time_range'),
    )

    op.create_index('ix_action_detections_video_job_id', 'action_detections', ['video_job_id'])
    op.create_index('ix_action_detections_track_id', 'action_detections', ['track_id'])
    op.create_index('ix_action_detections_action_type', 'action_detections', ['action_type'])
    op.create_index('ix_action_detections_mapped_player_id', 'action_detections', ['mapped_player_id'])


def downgrade() -> None:
    op.drop_index('ix_action_detections_mapped_player_id', table_name='action_detections')
    op.drop_index('ix_action_detections_action_type', table_name='action_detections')
    op.drop_index('ix_action_detections_track_id', table_name='action_detections')
    op.drop_index('ix_action_detections_video_job_id', table_name='action_detections')
    op.drop_table('action_detections')
