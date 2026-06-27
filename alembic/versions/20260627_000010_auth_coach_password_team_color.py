"""Add password_hash to coaches and color to teams (auth milestone)

Revision ID: 20260627_000010
Revises: 20260615_000009
Create Date: 2026-06-27 00:00:10

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260627_000010"
down_revision: str | None = "20260615_000009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add hashed-password column to coaches.
    # server_default="" lets existing rows (e.g. the seeded coach) stay
    # valid; they will be unusable for login until a real password is set.
    op.add_column(
        "coaches",
        sa.Column(
            "password_hash",
            sa.String(length=255),
            nullable=False,
            server_default="",
        ),
    )
    # Remove the server_default now that the column exists; new rows must
    # supply a hash explicitly.
    op.alter_column("coaches", "password_hash", server_default=None)

    # Optional team badge color (hex string, e.g. "#1A73E8").
    op.add_column(
        "teams",
        sa.Column("color", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("teams", "color")
    op.drop_column("coaches", "password_hash")
