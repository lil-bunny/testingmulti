"""Placeholder revision so DBs stamped at ``20260516_01`` match the migration graph.

Alembic always loads the revision id stored in ``alembic_version``; if no file declares
that id, ``upgrade head`` fails with “Can't locate revision”.

Revision ID: 20260516_01
Revises: 20260515_01
Create Date: 2026-05-16
"""

from typing import Sequence, Union

revision: str = "20260516_01"
down_revision: Union[str, Sequence[str], None] = "20260515_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
