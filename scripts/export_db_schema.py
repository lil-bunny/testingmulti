"""Export PostgreSQL schema metadata (no row data).

Collects tables, columns, indexes, foreign keys, constraints, enums, sequences,
views, and optional Python domain enums from ``app/models/``.

Usage:
  uv run python scripts/export_db_schema.py
  uv run python scripts/export_db_schema.py --output schema.json
  uv run python scripts/export_db_schema.py --schema public --pretty
  uv run python scripts/export_db_schema.py --format ddl --output schema.sql
  uv run python scripts/export_db_schema.py --include-python-models
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import subprocess
import sys
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import psycopg
from dotenv import load_dotenv
from psycopg.rows import dict_row

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _database_url() -> str:
    """Build Postgres URL from ``.env`` without loading full app ``Settings``."""
    load_dotenv(_ROOT / ".env.staging", override=False)
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


def _json_default(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _fetch_enums(conn: psycopg.Connection, schema: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            t.typname AS enum_name,
            array_agg(e.enumlabel ORDER BY e.enumsortorder) AS labels
        FROM pg_type t
        JOIN pg_enum e ON e.enumtypid = t.oid
        JOIN pg_namespace n ON n.oid = t.typnamespace
        WHERE n.nspname = %(schema)s
        GROUP BY t.typname
        ORDER BY t.typname
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"schema": schema})
        rows = cur.fetchall()
    return [
        {"name": row["enum_name"], "labels": list(row["labels"] or [])}
        for row in rows
    ]


def _fetch_tables(conn: psycopg.Connection, schema: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            c.table_name,
            obj_description(
                (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                'pg_class'
            ) AS comment
        FROM information_schema.tables c
        WHERE c.table_schema = %(schema)s
          AND c.table_type = 'BASE TABLE'
        ORDER BY c.table_name
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"schema": schema})
        table_rows = cur.fetchall()

    columns_sql = """
        SELECT
            c.table_name,
            c.column_name,
            c.ordinal_position,
            c.data_type,
            c.udt_name,
            c.is_nullable,
            c.column_default,
            c.character_maximum_length,
            c.numeric_precision,
            c.numeric_scale,
            col_description(
                (quote_ident(c.table_schema) || '.' || quote_ident(c.table_name))::regclass,
                c.ordinal_position
            ) AS comment
        FROM information_schema.columns c
        WHERE c.table_schema = %(schema)s
        ORDER BY c.table_name, c.ordinal_position
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(columns_sql, {"schema": schema})
        column_rows = cur.fetchall()

    columns_by_table: dict[str, list[dict[str, Any]]] = {}
    for row in column_rows:
        columns_by_table.setdefault(row["table_name"], []).append(
            {
                "name": row["column_name"],
                "ordinal_position": row["ordinal_position"],
                "data_type": row["data_type"],
                "udt_name": row["udt_name"],
                "nullable": row["is_nullable"] == "YES",
                "default": row["column_default"],
                "max_length": row["character_maximum_length"],
                "numeric_precision": row["numeric_precision"],
                "numeric_scale": row["numeric_scale"],
                "comment": row["comment"],
            }
        )

    return [
        {
            "name": row["table_name"],
            "comment": row["comment"],
            "columns": columns_by_table.get(row["table_name"], []),
        }
        for row in table_rows
    ]


def _fetch_primary_keys(conn: psycopg.Connection, schema: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            tc.table_name,
            tc.constraint_name,
            array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS columns
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = %(schema)s
          AND tc.constraint_type = 'PRIMARY KEY'
        GROUP BY tc.table_name, tc.constraint_name
        ORDER BY tc.table_name
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"schema": schema})
        rows = cur.fetchall()
    return [
        {
            "table": row["table_name"],
            "constraint_name": row["constraint_name"],
            "columns": list(row["columns"] or []),
        }
        for row in rows
    ]


def _fetch_foreign_keys(conn: psycopg.Connection, schema: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            tc.constraint_name,
            tc.table_name AS source_table,
            kcu.column_name AS source_column,
            ccu.table_name AS target_table,
            ccu.column_name AS target_column,
            rc.update_rule,
            rc.delete_rule
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON ccu.constraint_name = tc.constraint_name
         AND ccu.table_schema = tc.table_schema
        JOIN information_schema.referential_constraints rc
          ON rc.constraint_name = tc.constraint_name
         AND rc.constraint_schema = tc.table_schema
        WHERE tc.table_schema = %(schema)s
          AND tc.constraint_type = 'FOREIGN KEY'
        ORDER BY tc.table_name, tc.constraint_name, kcu.ordinal_position
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"schema": schema})
        rows = cur.fetchall()
    return [
        {
            "constraint_name": row["constraint_name"],
            "source_table": row["source_table"],
            "source_column": row["source_column"],
            "target_table": row["target_table"],
            "target_column": row["target_column"],
            "on_update": row["update_rule"],
            "on_delete": row["delete_rule"],
        }
        for row in rows
    ]


def _fetch_unique_constraints(
    conn: psycopg.Connection, schema: str
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            tc.table_name,
            tc.constraint_name,
            array_agg(kcu.column_name ORDER BY kcu.ordinal_position) AS columns
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        WHERE tc.table_schema = %(schema)s
          AND tc.constraint_type = 'UNIQUE'
        GROUP BY tc.table_name, tc.constraint_name
        ORDER BY tc.table_name, tc.constraint_name
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"schema": schema})
        rows = cur.fetchall()
    return [
        {
            "table": row["table_name"],
            "constraint_name": row["constraint_name"],
            "columns": list(row["columns"] or []),
        }
        for row in rows
    ]


def _fetch_check_constraints(
    conn: psycopg.Connection, schema: str
) -> list[dict[str, Any]]:
    sql = """
        SELECT
            rel.relname AS table_name,
            con.conname AS constraint_name,
            pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        WHERE nsp.nspname = %(schema)s
          AND con.contype = 'c'
        ORDER BY rel.relname, con.conname
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"schema": schema})
        rows = cur.fetchall()
    return [
        {
            "table": row["table_name"],
            "constraint_name": row["constraint_name"],
            "definition": row["definition"],
        }
        for row in rows
    ]


def _fetch_indexes(conn: psycopg.Connection, schema: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            tablename AS table_name,
            indexname AS index_name,
            indexdef AS definition
        FROM pg_indexes
        WHERE schemaname = %(schema)s
        ORDER BY tablename, indexname
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"schema": schema})
        rows = cur.fetchall()
    return [
        {
            "table": row["table_name"],
            "name": row["index_name"],
            "definition": row["definition"],
        }
        for row in rows
    ]


def _fetch_sequences(conn: psycopg.Connection, schema: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            sequence_name,
            data_type,
            start_value,
            minimum_value,
            maximum_value,
            increment,
            cycle_option
        FROM information_schema.sequences
        WHERE sequence_schema = %(schema)s
        ORDER BY sequence_name
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"schema": schema})
        rows = cur.fetchall()
    return [
        {
            "name": row["sequence_name"],
            "data_type": row["data_type"],
            "start_value": row["start_value"],
            "minimum_value": row["minimum_value"],
            "maximum_value": row["maximum_value"],
            "increment": row["increment"],
            "cycle": row["cycle_option"] == "YES",
        }
        for row in rows
    ]


def _fetch_views(conn: psycopg.Connection, schema: str) -> list[dict[str, Any]]:
    sql = """
        SELECT
            table_name AS view_name,
            view_definition
        FROM information_schema.views
        WHERE table_schema = %(schema)s
        ORDER BY table_name
    """
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, {"schema": schema})
        rows = cur.fetchall()
    return [
        {"name": row["view_name"], "definition": row["view_definition"]}
        for row in rows
    ]


def _collect_python_enums() -> list[dict[str, Any]]:
    models_dir = _ROOT / "app" / "models"
    results: list[dict[str, Any]] = []
    for path in sorted(models_dir.glob("*.py")):
        if path.name == "__init__.py":
            continue
        module_name = f"app.models.{path.stem}"
        module = importlib.import_module(module_name)
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module_name:
                continue
            if not issubclass(obj, Enum):
                continue
            members = [member.value for member in obj]
            results.append(
                {
                    "module": module_name,
                    "class_name": name,
                    "base": obj.__bases__[0].__name__,
                    "members": members,
                }
            )
    return sorted(results, key=lambda item: (item["module"], item["class_name"]))


def _export_schema_json(
    conn: psycopg.Connection,
    *,
    schema: str,
    include_python_models: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "database": conn.info.dbname,
        "schema": schema,
        "exported_at": datetime.now().astimezone().isoformat(),
        "enums": _fetch_enums(conn, schema),
        "tables": _fetch_tables(conn, schema),
        "primary_keys": _fetch_primary_keys(conn, schema),
        "foreign_keys": _fetch_foreign_keys(conn, schema),
        "unique_constraints": _fetch_unique_constraints(conn, schema),
        "check_constraints": _fetch_check_constraints(conn, schema),
        "indexes": _fetch_indexes(conn, schema),
        "sequences": _fetch_sequences(conn, schema),
        "views": _fetch_views(conn, schema),
    }
    if include_python_models:
        payload["python_enums"] = _collect_python_enums()
    return payload


def _export_schema_ddl(*, schema: str, output: Path | None) -> str:
    load_dotenv(_ROOT / ".env", override=False)
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

    env = os.environ.copy()
    env["PGPASSWORD"] = str(password)
    cmd = [
        "pg_dump",
        "--schema-only",
        "--no-owner",
        "--no-privileges",
        "--schema",
        schema,
        "-h",
        str(host),
        "-p",
        str(port),
        "-U",
        str(user),
        str(name),
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
    except FileNotFoundError as exc:
        raise SystemExit(
            "pg_dump not found on PATH. Install PostgreSQL client tools or use "
            "--format json (default)."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"pg_dump failed:\n{exc.stderr}") from exc

    ddl = completed.stdout
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(ddl, encoding="utf-8")
    return ddl


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export PostgreSQL schema metadata without row data."
    )
    parser.add_argument(
        "--schema",
        default="public",
        help="PostgreSQL schema to inspect (default: public).",
    )
    parser.add_argument(
        "--format",
        choices=("json", "ddl"),
        default="json",
        help="Output format: structured JSON (default) or pg_dump DDL.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write output to this file instead of stdout.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Pretty-print JSON output.",
    )
    parser.add_argument(
        "--include-python-models",
        action="store_true",
        help="Include Python Enum classes from app/models/ in JSON output.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.format == "ddl":
        ddl = _export_schema_ddl(schema=args.schema, output=args.output)
        if args.output is None:
            sys.stdout.write(ddl)
        else:
            print(f"Wrote DDL schema to {args.output}")
        return

    with psycopg.connect(_database_url()) as conn:
        payload = _export_schema_json(
            conn,
            schema=args.schema,
            include_python_models=args.include_python_models,
        )

    indent = 2 if args.pretty else None
    rendered = json.dumps(payload, indent=indent, default=_json_default)

    if args.output is None:
        sys.stdout.write(rendered)
        if not rendered.endswith("\n"):
            sys.stdout.write("\n")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
        print(f"Wrote schema JSON to {args.output}")


if __name__ == "__main__":
    main()
