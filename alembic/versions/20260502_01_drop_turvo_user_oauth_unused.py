"""Drop turvo_user_oauth (unused; OAuth lives in tenants.config).

Revision ID: 20260502_01
Revises: 20260501_01
Create Date: 2026-05-02
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260502_01"
down_revision: Union[str, Sequence[str], None] = "20260501_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS turvo_user_oauth")


def downgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS turvo_user_oauth (
            app_user_id TEXT PRIMARY KEY,
            turvo_username TEXT NOT NULL,
            turvo_password_ciphertext TEXT NOT NULL,
            access_token TEXT,
            refresh_token TEXT,
            token_type TEXT,
            access_token_expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_turvo_user_oauth_updated_at ON turvo_user_oauth(updated_at)"
    )
