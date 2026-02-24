"""initial starhoop schema

Revision ID: 20260224_000001
Revises:
Create Date: 2026-02-24 00:00:01

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260224_000001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "coaches",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("ix_coaches_email", "coaches", ["email"], unique=True)

    op.create_table(
        "teams",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("coach_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("logo_url", sa.String(length=1024), nullable=True),
        sa.Column("season", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["coach_id"], ["coaches.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("coach_id", "name", "season", name="uq_teams_coach_name_season"),
    )
    op.create_index("ix_teams_coach_id", "teams", ["coach_id"], unique=False)

    op.create_table(
        "players",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=False),
        sa.Column("jersey_number", sa.Integer(), nullable=False),
        sa.Column("photo_url", sa.String(length=1024), nullable=True),
        sa.Column("birth_year", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("jersey_number >= 0 AND jersey_number <= 99", name="ck_players_jersey_range"),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("team_id", "jersey_number", name="uq_players_team_jersey_number"),
    )
    op.create_index("ix_players_team_id", "players", ["team_id"], unique=False)
    op.create_index("ix_players_team_id_jersey_number", "players", ["team_id", "jersey_number"], unique=False)

    op.create_table(
        "highlights",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("player_id", sa.BigInteger(), nullable=False),
        sa.Column("video_url", sa.String(length=1024), nullable=False),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("event_timestamp_sec", sa.Numeric(10, 3), nullable=False),
        sa.Column("source_video_id", sa.String(length=255), nullable=True),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("event_timestamp_sec >= 0", name="ck_highlights_event_timestamp_non_negative"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_highlights_player_id", "highlights", ["player_id"], unique=False)
    op.create_index("ix_highlights_player_id_captured_at", "highlights", ["player_id", "captured_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_highlights_player_id_captured_at", table_name="highlights")
    op.drop_index("ix_highlights_player_id", table_name="highlights")
    op.drop_table("highlights")

    op.drop_index("ix_players_team_id_jersey_number", table_name="players")
    op.drop_index("ix_players_team_id", table_name="players")
    op.drop_table("players")

    op.drop_index("ix_teams_coach_id", table_name="teams")
    op.drop_table("teams")

    op.drop_index("ix_coaches_email", table_name="coaches")
    op.drop_table("coaches")
