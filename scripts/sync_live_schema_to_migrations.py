"""Align a live PostgreSQL database with Alembic revision targets.

Brings an existing database (e.g. staging exported in ``schema.json``) in line with:

- ``alembic/versions/20260521_01_identity_rbac.py`` (tenants + RBAC)
- ``alembic/versions/20260525_01_initial_schema.py`` (application schema)

Does **not** drop LangGraph checkpoint tables, ``organizations``, or
``alembic_version_freightx_api``. Idempotent checks skip work already applied.

Usage:
  uv run python scripts/sync_live_schema_to_migrations.py --dry-run
  uv run python scripts/sync_live_schema_to_migrations.py --apply
  uv run python scripts/sync_live_schema_to_migrations.py --apply --stamp-alembic
  uv run python scripts/sync_live_schema_to_migrations.py --apply --env-file .env.staging
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable
from pathlib import Path
from urllib.parse import quote_plus

import psycopg
from dotenv import load_dotenv
from psycopg import sql

_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_HEAD = "20260525_01"
RBAC_REVISION = "20260521_01"


def _database_url(env_file: Path | None) -> str:
    if env_file is not None:
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(_ROOT / ".env", override=False)
        load_dotenv(_ROOT / ".env.staging", override=True)

    host = os.environ.get("DATABASE_HOST")
    port = os.environ.get("DATABASE_PORT")
    name = os.environ.get("DATABASE_NAME")
    user = os.environ.get("DATABASE_USER")
    password = os.environ.get("DATABASE_PASSWORD")
    if not all([host, port, name, user, password]):
        raise SystemExit(
            "Database env vars not configured "
            "(DATABASE_HOST, DATABASE_PORT, DATABASE_NAME, "
            "DATABASE_USER, DATABASE_PASSWORD)"
        )
    encoded_password = quote_plus(str(password))
    return f"postgresql://{user}:{encoded_password}@{host}:{port}/{name}"


def _table_exists(cur: psycopg.Cursor, schema: str, table: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = %s AND table_name = %s
        )
        """,
        (schema, table),
    )
    return bool(cur.fetchone()[0])


def _column_exists(cur: psycopg.Cursor, schema: str, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s AND column_name = %s
        )
        """,
        (schema, table, column),
    )
    return bool(cur.fetchone()[0])


def _column_is_nullable(
    cur: psycopg.Cursor, schema: str, table: str, column: str
) -> bool | None:
    cur.execute(
        """
        SELECT is_nullable
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s AND column_name = %s
        """,
        (schema, table, column),
    )
    row = cur.fetchone()
    if row is None:
        return None
    return row[0] == "YES"


def _index_exists(cur: psycopg.Cursor, schema: str, name: str) -> bool:
    cur.execute(
        """
        SELECT EXISTS (
            SELECT 1 FROM pg_indexes
            WHERE schemaname = %s AND indexname = %s
        )
        """,
        (schema, name),
    )
    return bool(cur.fetchone()[0])


def _enum_labels(cur: psycopg.Cursor, schema: str, enum_name: str) -> list[str]:
    cur.execute(
        """
        SELECT e.enumlabel
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = %s AND t.typname = %s
        ORDER BY e.enumsortorder
        """,
        (schema, enum_name),
    )
    return [row[0] for row in cur.fetchall()]


def _fk_on_delete(
    cur: psycopg.Cursor, schema: str, table: str, column: str
) -> str | None:
    cur.execute(
        """
        SELECT rc.delete_rule
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.referential_constraints rc
          ON rc.constraint_name = tc.constraint_name
         AND rc.constraint_schema = tc.table_schema
        WHERE tc.table_schema = %s
          AND tc.table_name = %s
          AND tc.constraint_type = 'FOREIGN KEY'
          AND kcu.column_name = %s
        LIMIT 1
        """,
        (schema, table, column),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _fk_constraint_name(
    cur: psycopg.Cursor, schema: str, table: str, column: str
) -> str | None:
    cur.execute(
        """
        SELECT tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = %s
          AND tc.table_name = %s
          AND tc.constraint_type = 'FOREIGN KEY'
          AND kcu.column_name = %s
        LIMIT 1
        """,
        (schema, table, column),
    )
    row = cur.fetchone()
    return row[0] if row else None


class SyncRunner:
    def __init__(self, *, schema: str, dry_run: bool) -> None:
        self.schema = schema
        self.dry_run = dry_run
        self.planned: list[str] = []
        self.skipped: list[str] = []

    def run_sql(self, cur: psycopg.Cursor, statement: str, *, reason: str) -> None:
        if self.dry_run:
            self.planned.append(f"-- {reason}\n{statement.strip()}\n")
            return
        cur.execute(statement)

    def skip(self, message: str) -> None:
        self.skipped.append(message)

    def sync_extension(self, cur: psycopg.Cursor) -> None:
        self.run_sql(
            cur,
            "CREATE EXTENSION IF NOT EXISTS pgcrypto",
            reason="ensure pgcrypto (initial migration)",
        )

    def sync_rbac_tenants(self, cur: psycopg.Cursor) -> None:
        if not _table_exists(cur, self.schema, "tenants"):
            self.skip("tenants table missing — run Alembic RBAC revision first")
            return

        self.run_sql(
            cur,
            f"""
            UPDATE {self.schema}.tenants
            SET name = slug
            WHERE name IS NULL
            """,
            reason="backfill tenants.name before NOT NULL",
        )
        self.run_sql(
            cur,
            f"""
            UPDATE {self.schema}.tenants
            SET settings = '{{}}'::jsonb
            WHERE settings IS NULL
            """,
            reason="backfill tenants.settings before NOT NULL",
        )
        self.run_sql(
            cur,
            f"""
            UPDATE {self.schema}.tenants
            SET created_at = NOW()
            WHERE created_at IS NULL
            """,
            reason="backfill tenants.created_at before NOT NULL",
        )
        self.run_sql(
            cur,
            f"""
            UPDATE {self.schema}.tenants
            SET updated_at = NOW()
            WHERE updated_at IS NULL
            """,
            reason="backfill tenants.updated_at before NOT NULL",
        )

        alters = [
            ("name", "ALTER COLUMN name SET NOT NULL"),
            ("settings", "ALTER COLUMN settings SET NOT NULL"),
            ("created_at", "ALTER COLUMN created_at SET NOT NULL"),
            ("updated_at", "ALTER COLUMN updated_at SET NOT NULL"),
            (
                "slug",
                "ALTER COLUMN slug TYPE VARCHAR(64)",
            ),
        ]
        for _col, clause in alters:
            self.run_sql(
                cur,
                f"ALTER TABLE {self.schema}.tenants {clause}",
                reason=f"tenants {clause} (RBAC migration)",
            )

        if _index_exists(cur, self.schema, "tenants_slug_unique"):
            self.run_sql(
                cur,
                f"ALTER INDEX {self.schema}.tenants_slug_unique "
                f"RENAME TO uq_tenants_slug",
                reason="rename tenants_slug_unique -> uq_tenants_slug",
            )
        elif not _index_exists(cur, self.schema, "uq_tenants_slug"):
            self.run_sql(
                cur,
                f"""
                CREATE UNIQUE INDEX uq_tenants_slug
                ON {self.schema}.tenants (slug)
                """,
                reason="create uq_tenants_slug on tenants.slug",
            )
        else:
            self.skip("tenants slug uniqueness already named uq_tenants_slug")

    def sync_locations(self, cur: psycopg.Cursor) -> None:
        if not _table_exists(cur, self.schema, "locations"):
            self.skip("locations table missing")
            return
        if _column_exists(cur, self.schema, "locations", "state"):
            self.skip("locations.state already exists")
            return
        self.run_sql(
            cur,
            f"ALTER TABLE {self.schema}.locations ADD COLUMN state TEXT",
            reason="add locations.state (initial migration)",
        )

    def sync_documents_columns(self, cur: psycopg.Cursor) -> None:
        if not _table_exists(cur, self.schema, "documents"):
            self.skip("documents table missing")
            return

        if not _column_exists(cur, self.schema, "documents", "updated_at"):
            self.run_sql(
                cur,
                f"""
                ALTER TABLE {self.schema}.documents
                ADD COLUMN updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                """,
                reason="add documents.updated_at",
            )
        else:
            self.skip("documents.updated_at already exists")

        nullable = _column_is_nullable(cur, self.schema, "documents", "shipment_id")
        if nullable is False:
            self.run_sql(
                cur,
                f"ALTER TABLE {self.schema}.documents "
                f"ALTER COLUMN shipment_id DROP NOT NULL",
                reason="documents.shipment_id nullable (initial migration)",
            )
        elif nullable is True:
            self.skip("documents.shipment_id already nullable")

    def sync_document_analysis_columns(self, cur: psycopg.Cursor) -> None:
        if not _table_exists(cur, self.schema, "document_analysis"):
            self.skip("document_analysis table missing")
            return

        nullable = _column_is_nullable(
            cur, self.schema, "document_analysis", "shipment_id"
        )
        if nullable is False:
            self.run_sql(
                cur,
                f"ALTER TABLE {self.schema}.document_analysis "
                f"ALTER COLUMN shipment_id DROP NOT NULL",
                reason="document_analysis.shipment_id nullable (initial migration)",
            )
        elif nullable is True:
            self.skip("document_analysis.shipment_id already nullable")

    def sync_document_type_enum(self, cur: psycopg.Cursor) -> None:
        if not _table_exists(cur, self.schema, "documents"):
            self.skip("documents table missing — skip document_type enum sync")
            return

        labels = _enum_labels(cur, self.schema, "document_type")
        target = ["pod", "ratecon"]
        if labels == target:
            self.skip("document_type enum already matches migrations")
            return

        for index_name in (
            "uq_documents_one_pod_per_shipment",
            "idx_documents_shipment_id_type",
        ):
            if _index_exists(cur, self.schema, index_name):
                self.run_sql(
                    cur,
                    f"DROP INDEX {self.schema}.{index_name}",
                    reason=f"drop {index_name} before document_type enum swap",
                )

        self.run_sql(
            cur,
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1
                    FROM pg_type t
                    JOIN pg_namespace n ON n.oid = t.typnamespace
                    WHERE n.nspname = '{self.schema}'
                      AND t.typname = 'document_type_new'
                ) THEN
                    CREATE TYPE {self.schema}.document_type_new AS ENUM ('pod', 'ratecon');
                END IF;
            END
            $$;
            """,
            reason="create document_type_new enum (pod, ratecon)",
        )

        self.run_sql(
            cur,
            f"""
            ALTER TABLE {self.schema}.documents
            ALTER COLUMN type TYPE {self.schema}.document_type_new
            USING (
                CASE type::text
                    WHEN 'ratecon' THEN 'ratecon'::{self.schema}.document_type_new
                    ELSE 'pod'::{self.schema}.document_type_new
                END
            )
            """,
            reason="cast documents.type to document_type_new",
        )

        self.run_sql(
            cur,
            f"DROP TYPE {self.schema}.document_type",
            reason="drop legacy document_type enum",
        )
        self.run_sql(
            cur,
            f"ALTER TYPE {self.schema}.document_type_new RENAME TO document_type",
            reason="rename document_type_new -> document_type",
        )

    def sync_document_pod_dedupe(self, cur: psycopg.Cursor) -> None:
        if not _table_exists(cur, self.schema, "documents"):
            return
        self.run_sql(
            cur,
            f"""
            DELETE FROM {self.schema}.documents older
            USING {self.schema}.documents newer
            WHERE older.shipment_id IS NOT NULL
              AND older.shipment_id = newer.shipment_id
              AND older.type = 'pod'::document_type
              AND newer.type = 'pod'::document_type
              AND older.id <> newer.id
              AND (
                  older.created_at < newer.created_at
                  OR (
                      older.created_at = newer.created_at
                      AND older.id::text < newer.id::text
                  )
              )
            """,
            reason="keep one pod row per shipment before unique index",
        )

    def sync_foreign_keys(self, cur: psycopg.Cursor) -> None:
        specs = [
            (
                "documents",
                "shipment_id",
                "shipments",
                "id",
                "fk_documents_shipment_id",
            ),
            (
                "document_analysis",
                "shipment_id",
                "shipments",
                "id",
                "fk_document_analysis_shipment_id",
            ),
            (
                "document_analysis",
                "document_id",
                "documents",
                "id",
                "fk_document_analysis_document_id",
            ),
        ]
        for table, column, ref_table, ref_column, target_name in specs:
            if not _table_exists(cur, self.schema, table):
                continue
            rule = _fk_on_delete(cur, self.schema, table, column)
            if rule == "SET NULL":
                self.skip(f"{table}.{column} FK already ON DELETE SET NULL")
                continue
            if rule is None:
                self.skip(f"{table}.{column} FK missing — not creating automatically")
                continue

            existing = _fk_constraint_name(cur, self.schema, table, column)
            if existing:
                self.run_sql(
                    cur,
                    f"ALTER TABLE {self.schema}.{table} "
                    f"DROP CONSTRAINT {existing}",
                    reason=f"drop {table}.{column} FK for ON DELETE SET NULL",
                )
            self.run_sql(
                cur,
                f"""
                ALTER TABLE {self.schema}.{table}
                ADD CONSTRAINT {target_name}
                FOREIGN KEY ({column})
                REFERENCES {self.schema}.{ref_table}({ref_column})
                ON DELETE SET NULL
                """,
                reason=f"{table}.{column} ON DELETE SET NULL (initial migration)",
            )

    def sync_indexes(self, cur: psycopg.Cursor) -> None:
        if _index_exists(cur, self.schema, "idx_activity_logs_communication_id"):
            self.run_sql(
                cur,
                f"DROP INDEX {self.schema}.idx_activity_logs_communication_id",
                reason="remove index not in Alembic revisions",
            )
        else:
            self.skip("idx_activity_logs_communication_id already absent")

        index_sql = [
            (
                "uq_documents_one_pod_per_shipment",
                f"""
                CREATE UNIQUE INDEX uq_documents_one_pod_per_shipment
                ON {self.schema}.documents (shipment_id)
                WHERE type = 'pod'::document_type AND shipment_id IS NOT NULL
                """,
            ),
            (
                "idx_documents_shipment_id_type",
                f"""
                CREATE INDEX idx_documents_shipment_id_type
                ON {self.schema}.documents (shipment_id, type)
                WHERE shipment_id IS NOT NULL
                """,
            ),
            (
                "idx_document_analysis_document_id",
                f"""
                CREATE INDEX idx_document_analysis_document_id
                ON {self.schema}.document_analysis (document_id)
                WHERE document_id IS NOT NULL
                """,
            ),
        ]
        for name, statement in index_sql:
            if _index_exists(cur, self.schema, name):
                self.skip(f"index {name} already exists")
                continue
            self.run_sql(cur, statement, reason=f"create missing index {name}")

    def stamp_alembic(self, cur: psycopg.Cursor) -> None:
        if not _table_exists(cur, self.schema, "alembic_version"):
            self.skip("alembic_version table missing — skip stamp")
            return
        self.run_sql(
            cur,
            f"DELETE FROM {self.schema}.alembic_version",
            reason="reset alembic_version before stamp",
        )
        self.run_sql(
            cur,
            f"INSERT INTO {self.schema}.alembic_version (version_num) "
            f"VALUES ('{ALEMBIC_HEAD}')",
            reason=f"stamp alembic head at {ALEMBIC_HEAD}",
        )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sync live PostgreSQL schema with Alembic revisions "
            f"{RBAC_REVISION} + {ALEMBIC_HEAD}."
        )
    )
    parser.add_argument(
        "--schema",
        default="public",
        help="PostgreSQL schema to update (default: public).",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional .env file for DATABASE_* variables.",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned SQL without executing.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Execute sync statements in a single transaction.",
    )
    parser.add_argument(
        "--stamp-alembic",
        action="store_true",
        help="After sync, set alembic_version to head (20260525_01).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    runner = SyncRunner(schema=args.schema, dry_run=args.dry_run)
    url = _database_url(args.env_file)

    steps: list[tuple[str, Callable[[psycopg.Cursor], None]]] = [
        ("pgcrypto extension", runner.sync_extension),
        ("RBAC tenants", runner.sync_rbac_tenants),
        ("locations.state", runner.sync_locations),
        ("documents columns", runner.sync_documents_columns),
        ("document_analysis columns", runner.sync_document_analysis_columns),
        ("document_type enum", runner.sync_document_type_enum),
        ("POD row dedupe", runner.sync_document_pod_dedupe),
        ("foreign keys", runner.sync_foreign_keys),
        ("indexes", runner.sync_indexes),
    ]
    if args.stamp_alembic:
        steps.append(("alembic stamp", runner.stamp_alembic))

    if args.dry_run:
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                for label, step in steps:
                    step(cur)
        print(f"Planned sync for schema '{args.schema}' (dry-run):\n")
        print("\n".join(runner.planned) if runner.planned else "(no changes needed)")
        if runner.skipped:
            print("\nSkipped / already aligned:")
            for item in runner.skipped:
                print(f"  - {item}")
        return

    with psycopg.connect(url) as conn:
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SET search_path TO {}").format(
                        sql.Identifier(args.schema)
                    )
                )
                for label, step in steps:
                    print(f"Applying: {label}...")
                    step(cur)
        print(f"Schema sync applied on '{args.schema}'.")

    if runner.skipped:
        print("\nSkipped / already aligned:")
        for item in runner.skipped:
            print(f"  - {item}")

    print(
        "\nNext: re-export schema and compare:\n"
        "  uv run python scripts/export_db_schema.py --output schema.json --pretty\n"
        "  uv run python scripts/compare_schema_to_migrations.py"
    )


if __name__ == "__main__":
    main()
