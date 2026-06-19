"""Add ``pause_type`` to workflow lifecycles and ``exception`` activity log type.

Revision ID: 20260617_01
Revises: 20260525_01
Create Date: 2026-06-17

- ``lifecycle_pause_type`` on ``workflow_lifecycles`` — why a lifecycle is paused
  (system error vs. business exception) for review-queue routing.
- ``exception`` value on ``activity_log_type`` — snapshot row for catalog failures
  (same lifecycle semantics as ``action``).
- Backfill ``pause_type`` only when the lifecycle's latest activity log is ``exception``,
  using ``metadata.error_category`` on that row (lifecycles that moved on are skipped).
- Backfill ``activity_type = exception`` on rows linked to a sent workflow error alert
  email (``metadata.alert_type`` / ``communications``), merging catalog error fields.
- Clear error metadata from sibling ``status_change`` rows once merged into ``exception``.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20260617_01"
down_revision: Union[str, Sequence[str], None] = "20260525_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL requires new enum values to be committed before use in CHECK.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE activity_log_type ADD VALUE IF NOT EXISTS 'exception'"
        )
    op.execute(
        """
        CREATE TYPE lifecycle_pause_type AS ENUM (
            'system_error',
            'business_exception'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE workflow_lifecycles
        ADD COLUMN IF NOT EXISTS pause_type lifecycle_pause_type
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
        DROP CONSTRAINT IF EXISTS activity_logs_action_snapshot_chk
        """
    )
    # Pre-migration error alerts linked outbound email on an ``action`` row
    # (``metadata.alert_type = workflow_error_alert``). Reclassify as ``exception``
    # and merge catalog error fields from the sibling failure log on the lifecycle.
    op.execute(
        """
        UPDATE activity_logs al
        SET
            activity_type = 'exception',
            metadata = al.metadata
                || COALESCE(
                    (
                        SELECT jsonb_strip_nulls(
                            jsonb_build_object(
                                'error', e.metadata->>'error',
                                'error_category', e.metadata->>'error_category',
                                'error_description', e.metadata->>'error_description'
                            )
                        )
                        FROM activity_logs e
                        WHERE e.workflow_lifecycle_id = al.workflow_lifecycle_id
                          AND e.metadata->>'error' IS NOT NULL
                          AND e.id <> al.id
                          AND (
                            e.metadata->>'error' = al.metadata->>'error_code'
                            OR al.metadata->>'error_code' IS NULL
                          )
                        ORDER BY e.created_at DESC
                        LIMIT 1
                    ),
                    '{}'::jsonb
                )
                || CASE
                    WHEN al.metadata->>'error' IS NULL
                         AND al.metadata->>'error_code' IS NOT NULL
                        THEN jsonb_build_object(
                            'error', al.metadata->>'error_code'
                        )
                    ELSE '{}'::jsonb
                  END
        WHERE al.activity_type <> 'exception'
          AND al.communication_id IS NOT NULL
          AND (
            al.metadata->>'alert_type' = 'workflow_error_alert'
            OR EXISTS (
                SELECT 1
                FROM communications c
                WHERE c.id = al.communication_id
                  AND (
                    c.metadata->>'source' = 'workflow_error_alert'
                    OR c.metadata->>'alert_type' = 'workflow_error_alert'
                  )
            )
          )
        """
    )
    op.execute(
        """
        UPDATE activity_logs sc
        SET metadata = '{}'::jsonb
        WHERE sc.activity_type = 'status_change'
          AND sc.metadata->>'error' IS NOT NULL
          AND EXISTS (
            SELECT 1
            FROM activity_logs ex
            WHERE ex.workflow_lifecycle_id = sc.workflow_lifecycle_id
              AND ex.activity_type = 'exception'
              AND ex.metadata->>'error' = sc.metadata->>'error'
          )
        """
    )
    # Only lifecycles still paused on an exception (latest log is exception), not those
    # that progressed with newer tender/reminder activity after the failure email.
    op.execute(
        """
        UPDATE workflow_lifecycles wl
        SET pause_type = CASE
            WHEN latest_log.error_category = 'business'
                THEN 'business_exception'::lifecycle_pause_type
            ELSE 'system_error'::lifecycle_pause_type
        END
        FROM (
            SELECT DISTINCT ON (al.workflow_lifecycle_id)
                al.workflow_lifecycle_id,
                al.activity_type,
                al.metadata->>'error_category' AS error_category
            FROM activity_logs al
            ORDER BY al.workflow_lifecycle_id, al.created_at DESC
        ) AS latest_log
        WHERE wl.id = latest_log.workflow_lifecycle_id
          AND wl.pause_type IS NULL
          AND latest_log.activity_type = 'exception'
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
        ADD CONSTRAINT activity_logs_action_snapshot_chk CHECK (
            activity_type NOT IN ('action', 'exception')
            OR (
                from_status = to_status
                AND from_sub_status = to_sub_status
            )
        )
        """
    )
    op.execute(
        "ALTER TABLE workflow_lifecycles ADD COLUMN IF NOT EXISTS metadata JSONB DEFAULT '{}'::jsonb NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS pause_type")
    op.execute("DROP TYPE IF EXISTS lifecycle_pause_type")
    op.execute(
        """
        ALTER TABLE activity_logs
        DROP CONSTRAINT IF EXISTS activity_logs_action_snapshot_chk
        """
    )
    # Restore catalog error metadata on status_change rows cleared during upgrade.
    op.execute(
        """
        UPDATE activity_logs sc
        SET metadata = jsonb_strip_nulls(
            jsonb_build_object(
                'error', ex.metadata->>'error',
                'error_category', ex.metadata->>'error_category',
                'error_description', ex.metadata->>'error_description',
                'tender_id', ex.metadata->>'tender_id'
            )
        )
        FROM activity_logs ex
        WHERE sc.workflow_lifecycle_id = ex.workflow_lifecycle_id
          AND sc.activity_type = 'status_change'
          AND sc.metadata = '{}'::jsonb
          AND sc.from_status IS DISTINCT FROM sc.to_status
          AND ex.activity_type = 'exception'
          AND ex.metadata->>'error' IS NOT NULL
        """
    )
    # Reclassify backfilled and post-migration exception rows before enum swap.
    op.execute(
        """
        UPDATE activity_logs
        SET activity_type = 'action'
        WHERE activity_type = 'exception'
        """
    )

    # Remove 'exception' from activity_log_type by recreating the enum.
    # PostgreSQL cannot DROP a single enum value, so we swap the type.
    op.execute(
        """
        CREATE TYPE activity_log_type_prev AS ENUM (
            'action',
            'status_change',
            'sub_status_change'
        )
        """
    )
    op.execute(
        """
        ALTER TABLE activity_logs
            ALTER COLUMN activity_type TYPE activity_log_type_prev
            USING activity_type::text::activity_log_type_prev
        """
    )
    op.execute("DROP TYPE activity_log_type")
    op.execute("ALTER TYPE activity_log_type_prev RENAME TO activity_log_type")

    # Restore the original action-only CHECK.
    op.execute(
        """
        ALTER TABLE activity_logs
        ADD CONSTRAINT activity_logs_action_snapshot_chk CHECK (
            activity_type <> 'action'
            OR (
                from_status = to_status
                AND from_sub_status = to_sub_status
            )
        )
        """
    )
    op.execute("ALTER TABLE workflow_lifecycles DROP COLUMN IF EXISTS metadata")
