"""add users.avatar_url

Revision ID: c8f2a6d41e37
Revises: e4a7c2d9b815
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8f2a6d41e37"
down_revision: str | Sequence[str] | None = "e4a7c2d9b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
