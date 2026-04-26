"""Milestone 3 Phase 2: Jersey detection aggregation table for player mapping.

Revision ID: 20260427_000003
Revises: 20260307_000002
Create Date: 2026-04-27 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '20260427_000003'
down_revision = '20260307_000002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create jersey_detections table
    op.create_table(
        'jersey_detections',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('video_job_id', sa.Integer(), nullable=False),
        sa.Column('track_id', sa.Integer(), nullable=False),
        sa.Column('detected_jersey_number', sa.Integer(), nullable=False),
        sa.Column('jersey_confidence', sa.Float(), nullable=False),
        sa.Column('frame_count', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('confidence_mean', sa.Float(), nullable=False),
        sa.Column('confidence_max', sa.Float(), nullable=False),
        sa.Column('mapped_player_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['video_job_id'], ['video_jobs.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['mapped_player_id'], ['players.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('video_job_id', 'track_id', name='uq_jersey_detections_job_track'),
        sa.CheckConstraint('detected_jersey_number >= 0 AND detected_jersey_number <= 99', 
                          name='ck_jersey_detections_jersey_range'),
        sa.CheckConstraint('jersey_confidence >= 0.0 AND jersey_confidence <= 1.0', 
                          name='ck_jersey_detections_confidence_range'),
        sa.CheckConstraint('confidence_mean >= 0.0 AND confidence_mean <= 1.0', 
                          name='ck_jersey_detections_mean_confidence_range'),
        sa.CheckConstraint('confidence_max >= 0.0 AND confidence_max <= 1.0', 
                          name='ck_jersey_detections_max_confidence_range'),
    )
    # Create indexes for common queries
    op.create_index('ix_jersey_detections_video_job_id', 'jersey_detections', ['video_job_id'])
    op.create_index('ix_jersey_detections_track_id', 'jersey_detections', ['track_id'])
    op.create_index('ix_jersey_detections_mapped_player_id', 'jersey_detections', ['mapped_player_id'])


def downgrade() -> None:
    # Drop table and indexes
    op.drop_index('ix_jersey_detections_mapped_player_id', table_name='jersey_detections')
    op.drop_index('ix_jersey_detections_track_id', table_name='jersey_detections')
    op.drop_index('ix_jersey_detections_video_job_id', table_name='jersey_detections')
    op.drop_table('jersey_detections')
