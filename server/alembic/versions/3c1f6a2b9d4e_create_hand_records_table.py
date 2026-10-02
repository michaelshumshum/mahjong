"""create hand_records table

Revision ID: 3c1f6a2b9d4e
Revises: 95b97823dd97
Create Date: 2026-10-02 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c1f6a2b9d4e"
down_revision: str | Sequence[str] | None = "95b97823dd97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "hand_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("engine_version", sa.String(length=32), nullable=False),
        sa.Column("ruleset", _JSON, nullable=False),
        sa.Column("seed", sa.BigInteger(), nullable=False),
        sa.Column("dealer", sa.Integer(), nullable=False),
        sa.Column("prevailing", sa.Integer(), nullable=False),
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
    op.drop_table("hand_records")
