"""
Dev-only: reset ratecon + pod_lifecycle workflow artifacts for one shipment.

Keeps: tenants, shipments row, locations, tenders/load_tendering, tenant settings.
Removes: workflow_lifecycles (ratecon/pod_lifecycle), workflow_runs, activity_logs,
         documents + document_analysis for that shipment, comms tied to those runs.

Usage:
  uv run python scripts/reset_shipment_ratecon_pod_state.py --shipment-number 1000324895
  uv run python scripts/reset_shipment_ratecon_pod_state.py --shipment-number 1000324895 --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from sqlalchemy import text

from app.core.db import db_scope
from app.repositories.tenants_db_repository import find_tenant_uuid_by_slug

_WORKFLOWS = ("ratecon", "pod_lifecycle")


def _count(session, sql: str, params: dict) -> int:
    row = session.execute(text(sql), params).fetchone()
    return int(row[0]) if row else 0


def reset_shipment(*, tenant_slug: str, shipment_number: str, dry_run: bool) -> None:
    tenant_id = find_tenant_uuid_by_slug(tenant_slug.strip())
    if not tenant_id:
        raise SystemExit(f"tenant slug not found: {tenant_slug!r}")

    with db_scope() as repos:
        session = repos.session
        ship = session.execute(
            text(
                """
                SELECT id::text, shipment_number
                FROM shipments
                WHERE tenant_id = CAST(:tenant_id AS uuid)
                  AND shipment_number = :shipment_number
                LIMIT 1
                """
            ),
            {"tenant_id": tenant_id, "shipment_number": shipment_number.strip()},
        ).fetchone()
        if not ship:
            raise SystemExit(
                f"shipment not found tenant={tenant_slug!r} shipment_number={shipment_number!r}"
            )
        shipments_row_id = ship[0]
        print(f"shipment: {ship[1]} id={shipments_row_id} tenant={tenant_slug}")

        lifecycle_ids = [
            str(r[0])
            for r in session.execute(
                text(
                    """
                    SELECT id FROM workflow_lifecycles
                    WHERE tenant_id = CAST(:tenant_id AS uuid)
                      AND shipment_id = CAST(:shipments_row_id AS uuid)
                      AND workflow_name = ANY(:workflows)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "shipments_row_id": shipments_row_id,
                    "workflows": list(_WORKFLOWS),
                },
            ).fetchall()
        ]
        run_ids = [
            str(r[0])
            for r in session.execute(
                text(
                    """
                    SELECT id FROM workflow_runs
                    WHERE workflow_lifecycle_id = ANY(CAST(:lifecycle_ids AS uuid[]))
                    """
                ),
                {"lifecycle_ids": lifecycle_ids or ["00000000-0000-0000-0000-000000000000"]},
            ).fetchall()
        ] if lifecycle_ids else []

        before = {
            "lifecycles": len(lifecycle_ids),
            "runs": len(run_ids),
            "documents": _count(
                session,
                "SELECT COUNT(*) FROM documents WHERE shipment_id = CAST(:sid AS uuid)",
                {"sid": shipments_row_id},
            ),
            "document_analysis": _count(
                session,
                "SELECT COUNT(*) FROM document_analysis WHERE shipment_id = CAST(:sid AS uuid)",
                {"sid": shipments_row_id},
            ),
            "comms_on_runs": _count(
                session,
                "SELECT COUNT(*) FROM communications WHERE workflow_run_id = ANY(CAST(:run_ids AS uuid[]))",
                {"run_ids": run_ids or ["00000000-0000-0000-0000-000000000000"]},
            ),
        }
        print("before:", before)

        if dry_run:
            print("dry-run: no changes applied")
            return

        if run_ids:
            session.execute(
                text(
                    "DELETE FROM communications WHERE workflow_run_id = ANY(CAST(:run_ids AS uuid[]))"
                ),
                {"run_ids": run_ids},
            )

        if lifecycle_ids:
            session.execute(
                text("DELETE FROM workflow_lifecycles WHERE id = ANY(CAST(:ids AS uuid[]))"),
                {"ids": lifecycle_ids},
            )

        session.execute(
            text("DELETE FROM document_analysis WHERE shipment_id = CAST(:sid AS uuid)"),
            {"sid": shipments_row_id},
        )
        session.execute(
            text("DELETE FROM documents WHERE shipment_id = CAST(:sid AS uuid)"),
            {"sid": shipments_row_id},
        )
        session.commit()

        after = {
            "lifecycles": _count(
                session,
                """
                SELECT COUNT(*) FROM workflow_lifecycles
                WHERE shipment_id = CAST(:sid AS uuid)
                  AND workflow_name = ANY(:workflows)
                """,
                {"sid": shipments_row_id, "workflows": list(_WORKFLOWS)},
            ),
            "documents": _count(
                session,
                "SELECT COUNT(*) FROM documents WHERE shipment_id = CAST(:sid AS uuid)",
                {"sid": shipments_row_id},
            ),
            "document_analysis": _count(
                session,
                "SELECT COUNT(*) FROM document_analysis WHERE shipment_id = CAST(:sid AS uuid)",
                {"sid": shipments_row_id},
            ),
        }
        print("after:", after)
        print("done — shipment row kept; re-run ratecon email first, then route_complete / POD reply")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--shipment-number",
        required=True,
        help="Turvo shipment_number (e.g. 1000324895)",
    )
    parser.add_argument("--tenant-slug", default="t3ra")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    reset_shipment(
        tenant_slug=args.tenant_slug,
        shipment_number=args.shipment_number,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
