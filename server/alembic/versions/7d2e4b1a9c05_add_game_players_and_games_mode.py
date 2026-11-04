"""add game_players table and games.mode

Revision ID: 7d2e4b1a9c05
Revises: 3c1f6a2b9d4e
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7d2e4b1a9c05"
down_revision: str | Sequence[str] | None = "3c1f6a2b9d4e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("games", sa.Column("mode", sa.String(length=16), nullable=True))
    op.create_check_constraint("ck_games_mode", "games", "mode IN ('practice', 'multiplayer')")
    op.create_table(
        "game_players",
        sa.Column("game_id", sa.Integer(), nullable=False),
        sa.Column("seat", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("bot_tier", sa.String(length=16), nullable=True),
        sa.Column("final_score", sa.Integer(), nullable=False),
        sa.Column("placement", sa.SmallInteger(), nullable=False),
        sa.CheckConstraint("seat BETWEEN 0 AND 3", name="ck_game_players_seat"),
        sa.CheckConstraint("kind IN ('user', 'guest', 'bot')", name="ck_game_players_kind"),
        sa.CheckConstraint(
            "(kind = 'guest' AND user_id IS NULL AND bot_tier IS NULL)"
            " OR (kind = 'bot' AND user_id IS NULL AND bot_tier IS NOT NULL)"
            " OR (kind = 'user' AND bot_tier IS NULL)",
            name="ck_game_players_kind_pairing",
        ),
        sa.CheckConstraint("placement BETWEEN 1 AND 4", name="ck_game_players_placement"),
        sa.ForeignKeyConstraint(["game_id"], ["games.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("game_id", "seat"),
    )
    op.create_index(
        "ix_game_players_user_id_game_id",
        "game_players",
        ["user_id", sa.text("game_id DESC")],
        postgresql_where=sa.text("user_id IS NOT NULL"),
        sqlite_where=sa.text("user_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_game_players_user_id_game_id", table_name="game_players")
    op.drop_table("game_players")
    op.drop_constraint("ck_games_mode", "games", type_="check")
    op.drop_column("games", "mode")
