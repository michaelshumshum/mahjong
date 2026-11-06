"""clear training consents given under the draft wording

Revision ID: e4a7c2d9b815
Revises: 5b3e9c1d7a42
Create Date: 2026-11-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4a7c2d9b815"
down_revision: str | Sequence[str] | None = "5b3e9c1d7a42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# the phase 3 placeholder wording (ADR 0028); only consent-screen test users could sign in then
DRAFT_CONSENT_VERSION = "2026-11-draft"


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE users SET training_consent_at = NULL, consent_version = NULL"
            " WHERE consent_version = :draft"
        ).bindparams(draft=DRAFT_CONSENT_VERSION)
    )


def downgrade() -> None:
    # cleared consents aren't restored: a withdrawn consent is indistinguishable from none
    pass
