"""Compare schema.json export against Alembic migration files."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    schema_path = _ROOT / "schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    identity = (_ROOT / "alembic/versions/20260521_01_identity_rbac.py").read_text(
        encoding="utf-8"
    )
    initial = (_ROOT / "alembic/versions/20260525_01_initial_schema.py").read_text(
        encoding="utf-8"
    )

    identity_enums = {
        "platform_role": ["platform_super_admin"],
        "tenant_role": [
            "customer_admin",
            "customer_site_admin",
            "customer_site_supervisor",
        ],
        "tenant_membership_status": ["active", "invited", "inactive"],
    }

    initial_enums: dict[str, list[str]] = {}
    for match in re.finditer(r"CREATE TYPE (\w+) AS ENUM \((.*?)\)", initial, re.S):
        name = match.group(1)
        labels = [x.strip().strip("'") for x in re.findall(r"'([^']+)'", match.group(2))]
        initial_enums[name] = labels

    expected_enums = {**initial_enums, **identity_enums}

    initial_tables: dict[str, list[str]] = {}
    for match in re.finditer(r"CREATE TABLE (\w+) \((.*?)\n\s*\)", initial, re.S):
        tname = match.group(1)
        body = match.group(2)
        cols: list[str] = []
        for line in body.split("\n"):
            line = line.strip().rstrip(",")
            if not line or line.startswith("CONSTRAINT"):
                continue
            col_match = re.match(r"(\w+)\s+", line)
            if col_match and col_match.group(1).upper() not in ("CONSTRAINT", "FOREIGN"):
                cols.append(col_match.group(1))
        initial_tables[tname] = cols

    identity_tables = {
        "users": [
            "id",
            "email",
            "name",
            "password_hash",
            "platform_role",
            "is_active",
            "created_at",
            "updated_at",
        ],
        "tenant_sites": ["id", "tenant_id", "name", "code", "is_active", "created_at"],
        "tenant_memberships": [
            "id",
            "user_id",
            "tenant_id",
            "role",
            "status",
            "created_at",
        ],
        "tenant_site_users": ["user_id", "tenant_site_id"],
    }

    expected_tables = dict(initial_tables)
    expected_tables.setdefault(
        "tenants", ["id", "name", "slug", "settings", "created_at", "updated_at"]
    )
    expected_tables.update(identity_tables)

    idx_pattern = re.compile(r"CREATE (?:UNIQUE )?INDEX (\w+)\s+ON (\w+)", re.I)
    expected_indexes: dict[str, dict[str, str]] = {}
    for source_text, label in ((initial, "initial"), (identity, "identity")):
        for match in idx_pattern.finditer(source_text):
            expected_indexes[match.group(1)] = {
                "table": match.group(2),
                "source": label,
            }
    expected_indexes["uq_documents_one_pod_per_shipment"] = {
        "table": "documents",
        "source": "initial",
    }

    fk_re = re.compile(
        r"(\w+)\s+\w+[^,\n]*REFERENCES\s+(\w+)\((\w+)\)(?:\s+ON DELETE (\w+))?",
        re.I,
    )
    expected_fks: list[tuple[str, str, str, str, str]] = []
    for tname, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\s*\)", initial, re.S):
        for col_line in body.split("\n"):
            fk_match = fk_re.search(col_line)
            if fk_match:
                on_delete = (fk_match.group(4) or "NO ACTION").upper().replace(" ", "_")
                expected_fks.append(
                    (
                        tname,
                        fk_match.group(1),
                        fk_match.group(2),
                        fk_match.group(3),
                        on_delete,
                    )
                )

    expected_fks.extend(
        [
            ("tenant_sites", "tenant_id", "tenants", "id", "CASCADE"),
            ("tenant_memberships", "user_id", "users", "id", "CASCADE"),
            ("tenant_memberships", "tenant_id", "tenants", "id", "CASCADE"),
            ("tenant_site_users", "user_id", "users", "id", "CASCADE"),
            ("tenant_site_users", "tenant_site_id", "tenant_sites", "id", "CASCADE"),
        ]
    )

    live_enums = {item["name"]: item["labels"] for item in schema["enums"]}
    live_tables = {item["name"]: item for item in schema["tables"]}
    live_indexes = {item["name"]: item for item in schema["indexes"]}
    live_fks = schema["foreign_keys"]

    expected_table_names = set(expected_tables)
    live_table_names = set(live_tables)

    print("=" * 70)
    print("TABLES IN schema.json BUT NOT IN MIGRATIONS")
    print("=" * 70)
    extra_tables = sorted(live_table_names - expected_table_names)
    if extra_tables:
        for table in extra_tables:
            print(f"  + {table}")
    else:
        print("  (none)")

    print()
    print("TABLES IN MIGRATIONS BUT NOT IN schema.json")
    print("=" * 70)
    missing_tables = sorted(expected_table_names - live_table_names)
    if missing_tables:
        for table in missing_tables:
            print(f"  - {table}")
    else:
        print("  (none)")

    print()
    print("ENUM DIFFERENCES")
    print("=" * 70)
    for name in sorted(set(live_enums) | set(expected_enums)):
        live = live_enums.get(name)
        expected = expected_enums.get(name)
        if live is None:
            print(f"  - missing in schema.json: {name} expected={expected}")
            continue
        if expected is None:
            print(f"  + extra in schema.json: {name} labels={live}")
            continue
        if live != expected:
            only_live = sorted(set(live) - set(expected))
            only_expected = sorted(set(expected) - set(live))
            if only_live or only_expected:
                print(f"  ~ {name}:")
                if only_live:
                    print(f"      extra in schema.json: {only_live}")
                if only_expected:
                    print(f"      missing from schema.json: {only_expected}")

    print()
    print("COLUMN DIFFERENCES (shared tables)")
    print("=" * 70)
    column_diff = False
    for table in sorted(expected_table_names & live_table_names):
        expected_cols = set(expected_tables[table])
        live_cols = {col["name"] for col in live_tables[table]["columns"]}
        only_live = sorted(live_cols - expected_cols)
        only_expected = sorted(expected_cols - live_cols)
        if only_live or only_expected:
            column_diff = True
            print(f"  {table}:")
            if only_live:
                print(f"    + in schema.json only: {only_live}")
            if only_expected:
                print(f"    - in migrations only: {only_expected}")
    if not column_diff:
        print("  (none by name)")

    print()
    print("COLUMN NULLABILITY / TYPE DRIFT (notable)")
    print("=" * 70)
    for table_name in ("tenants", "locations", "data_imports", "documents"):
        if table_name not in live_tables:
            continue
        print(f"  {table_name}:")
        for col in live_tables[table_name]["columns"]:
            print(
                f"    {col['name']}: type={col['data_type']} udt={col['udt_name']} "
                f"nullable={col['nullable']} default={col['default']!r}"
            )

    print()
    print("INDEX DIFFERENCES")
    print("=" * 70)
    live_idx_names = set(live_indexes)
    expected_idx_names = set(expected_indexes)
    extra_idx = sorted(live_idx_names - expected_idx_names)
    missing_idx = sorted(expected_idx_names - live_idx_names)
    if extra_idx:
        for name in extra_idx:
            idx = live_indexes[name]
            print(f"  + {name} on {idx['table']}")
    if missing_idx:
        for name in missing_idx:
            idx = expected_indexes[name]
            print(f"  - {name} on {idx['table']} ({idx['source']})")
    if not extra_idx and not missing_idx:
        print("  (none by name)")

    print()
    print("FOREIGN KEY DIFFERENCES")
    print("=" * 70)
    live_fk_set = {
        (
            fk["source_table"],
            fk["source_column"],
            fk["target_table"],
            fk["target_column"],
            fk["on_delete"].upper(),
        )
        for fk in live_fks
    }
    expected_fk_set = set(expected_fks)
    extra_fks = sorted(live_fk_set - expected_fk_set)
    missing_fks = sorted(expected_fk_set - live_fk_set)
    if extra_fks:
        for fk in extra_fks:
            print(
                f"  + {fk[0]}.{fk[1]} -> {fk[2]}.{fk[3]} ON DELETE {fk[4]}"
            )
    if missing_fks:
        for fk in missing_fks:
            print(
                f"  - {fk[0]}.{fk[1]} -> {fk[2]}.{fk[3]} ON DELETE {fk[4]}"
            )
    if not extra_fks and not missing_fks:
        print("  (none)")

    print()
    print("UNIQUE CONSTRAINTS / CHECKS IN schema.json (for manual review)")
    print("=" * 70)
    for item in schema["unique_constraints"]:
        print(f"  unique {item['table']}.{item['constraint_name']}: {item['columns']}")
    for item in schema["check_constraints"]:
        print(f"  check {item['table']}.{item['constraint_name']}: {item['definition']}")


if __name__ == "__main__":
    main()
