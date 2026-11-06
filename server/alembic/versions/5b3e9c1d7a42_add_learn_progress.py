"""add learn_progress, learn_endless_scores, users.prefs and users.learn_imported_at

Revision ID: 5b3e9c1d7a42
Revises: aa6436689894
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b3e9c1d7a42"
down_revision: str | Sequence[str] | None = "aa6436689894"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "prefs",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            server_default=sa.text("'{}'"),
            nullable=False,
        ),
    )
    op.add_column(
        "users", sa.Column("learn_imported_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_table(
        "learn_progress",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("lesson_id", sa.String(length=64), nullable=False),
        sa.Column("solved", sa.Boolean(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("solved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("step", sa.Integer(), nullable=True),
        sa.Column("imported", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "lesson_id"),
    )
    op.create_table(
        "learn_endless_scores",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("streak", sa.Integer(), nullable=False),
        sa.Column("best", sa.Integer(), nullable=False),
        sa.Column("solved", sa.Integer(), nullable=False),
        sa.Column("imported", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "kind"),
    )


def downgrade() -> None:
    op.drop_table("learn_endless_scores")
    op.drop_table("learn_progress")
    op.drop_column("users", "learn_imported_at")
    op.drop_column("users", "prefs")
