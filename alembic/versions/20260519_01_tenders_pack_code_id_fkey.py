"""Replace ``tenders.pack_code`` composite FK with ``pack_code_id`` → ``pack_codes.id``.

Revision ID: 20260519_01
Revises: 20260518_01
Create Date: 2026-05-19
"""

from typing import Sequence, Union

from alembic import op


revision: str = "20260519_01"
down_revision: Union[str, Sequence[str], None] = "20260518_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenders
            ADD COLUMN IF NOT EXISTS pack_code_id UUID;
        """
    )
    op.execute(
        """
        UPDATE tenders t
        SET pack_code_id = pc.id
        FROM pack_codes pc
        WHERE t.pack_code_id IS NULL
          AND t.pack_code IS NOT NULL
          AND pc.tenant_id = t.tenant_id
          AND pc.pack_code = t.pack_code;
        """
    )
    op.execute(
        """
        ALTER TABLE tenders
            DROP CONSTRAINT IF EXISTS tenders_tenant_pack_code_fkey;
        """
    )
    op.execute(
        """
        ALTER TABLE tenders
            DROP COLUMN IF EXISTS pack_code;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE tenders
                ADD CONSTRAINT tenders_pack_code_id_fkey
                FOREIGN KEY (pack_code_id) REFERENCES pack_codes (id);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_tenders_pack_code_id
            ON tenders (pack_code_id);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE tenders
            ADD COLUMN IF NOT EXISTS pack_code TEXT;
        """
    )
    op.execute(
        """
        UPDATE tenders t
        SET pack_code = pc.pack_code
        FROM pack_codes pc
        WHERE t.pack_code IS NULL
          AND t.pack_code_id IS NOT NULL
          AND pc.id = t.pack_code_id;
        """
    )
    op.execute(
        """
        ALTER TABLE tenders
            DROP CONSTRAINT IF EXISTS tenders_pack_code_id_fkey;
        """
    )
    op.execute("DROP INDEX IF EXISTS idx_tenders_pack_code_id")
    op.execute(
        """
        ALTER TABLE tenders
            DROP COLUMN IF EXISTS pack_code_id;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            ALTER TABLE tenders
                ADD CONSTRAINT tenders_tenant_pack_code_fkey
                FOREIGN KEY (tenant_id, pack_code)
                REFERENCES pack_codes (tenant_id, pack_code);
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
