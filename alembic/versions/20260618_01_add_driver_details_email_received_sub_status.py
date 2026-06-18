"""Add driver_details_email_received to lifecycle_sub_status enum."""

from __future__ import annotations

from alembic import op

revision = "20260618_01"
down_revision = "20260617_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE lifecycle_sub_status ADD VALUE IF NOT EXISTS "
        "'driver_details_email_received'"
    )


def downgrade() -> None:
    # PostgreSQL does not support removing enum values safely.
    pass
