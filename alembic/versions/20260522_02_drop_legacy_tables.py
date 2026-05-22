"""Drop legacy tables unused by application code (greenfield bootstrap prep).

Revision ID: 20260522_02
Revises: 20260522_01
Create Date: 2026-05-22

Removes:
- ``documents1``: pre-UUID duplicate of ``documents`` (TEXT ids); no app references.
- ``turvo_user_oauth``: superseded by tenant config; prior drop revision left table on some DBs.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260522_02"
down_revision: Union[str, Sequence[str], None] = "20260522_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TABLE IF EXISTS documents1 CASCADE")
    op.execute("DROP TABLE IF EXISTS turvo_user_oauth CASCADE")


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
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS documents1 (
            id TEXT PRIMARY KEY,
            type document_type NOT NULL,
            shipment_id TEXT NOT NULL,
            object_key TEXT NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
