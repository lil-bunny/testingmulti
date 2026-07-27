"""Add pod_vs_tms_analysis to document_analysis_type (PoD-vs-TMS scoring).

Revision ID: 20260727_01
Revises: 20260723_01
Create Date: 2026-07-27

Additive enum widen only — ``pod_vs_ratecon_comparison`` remains on the type
for historical rows. New PoD scoring persists under ``pod_vs_tms_analysis``.
"""

from __future__ import annotations

from alembic import op

revision = "20260727_01"
down_revision = "20260723_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TYPE document_analysis_type ADD VALUE IF NOT EXISTS "
        "'pod_vs_tms_analysis'"
    )


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value safely while rows may reference it.
    pass
