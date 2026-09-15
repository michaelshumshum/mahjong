"""create games table

Revision ID: 95b97823dd97
Revises:
Create Date: 2026-09-16 01:03:26.371978

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "95b97823dd97"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "games",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("ruleset", _JSON, nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("action_log", _JSON, nullable=False),
        sa.Column("players", _JSON, nullable=False),
        sa.Column("result", _JSON, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("games")
