"""Integration tests for ShipmentsRepository (requires Postgres + migrations)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import psycopg
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import _session_factory
from app.repositories.shipments_repository import ShipmentsRepository

_TENANT_UUID = "00000000-0000-4000-8000-0000000000e1"


def _db_available() -> bool:
    url = (settings.DATABASE_URL or "").strip()
    if not url:
        return False
    try:
        with psycopg.connect(url) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'shipments'
                      AND column_name = 'shipment_number'
                    """
                )
                if cur.fetchone() is None:
                    return False
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'shipments'
                      AND column_name = 'delivery_address'
                    """
                )
                if cur.fetchone() is None:
                    return False
                cur.execute(
                    """
                    SELECT 1
                    FROM information_schema.columns
                    WHERE table_name = 'shipments'
                      AND column_name = 'delivery_date'
                    """
                )
                return cur.fetchone() is not None
    except Exception:
        return False


@pytest.fixture
def repo() -> Iterator[ShipmentsRepository]:
    session: Session = _session_factory()()
    try:
        yield ShipmentsRepository(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest.mark.skipif(not _db_available(), reason="DATABASE_URL unset or shipments migration missing")
def test_upsert_insert_and_conflict_merge_load_id(repo: ShipmentsRepository):
    number = f"test-{uuid.uuid4().hex[:12]}"
    first = repo.upsert_by_tenant_and_shipment_number_tx(
        tenant_id=_TENANT_UUID,
        shipment_number=number,
        metadata={"load_id": "LOAD-A"},
    )
    assert first.created is True

    second = repo.upsert_by_tenant_and_shipment_number_tx(
        tenant_id=_TENANT_UUID,
        shipment_number=number,
        metadata={"load_id": "LOAD-B", "tag": "v2"},
    )
    assert second.created is False
    assert second.shipment_id == first.shipment_id

    row = repo.get_by_tenant_and_shipment_number_tx(
        tenant_id=_TENANT_UUID,
        shipment_number=number,
    )
    assert row is not None
    assert row["metadata"]["load_id"] == "LOAD-B"
    assert row["metadata"]["tag"] == "v2"


@pytest.mark.skipif(not _db_available(), reason="DATABASE_URL unset or shipments migration missing")
def test_update_location_ids_persists_delivery_address(repo: ShipmentsRepository) -> None:
    location_ids = _any_two_location_ids()
    if not location_ids:
        pytest.skip("no locations rows available for FK test")

    number = f"test-{uuid.uuid4().hex[:12]}"
    upsert = repo.upsert_by_tenant_and_shipment_number_tx(
        tenant_id=_TENANT_UUID,
        shipment_number=number,
        metadata={"load_id": "LOAD-X"},
    )
    delivery_address = {
        "name": "RENO DC",
        "address1": "123 Main St",
        "city": "RENO",
        "state": "NV",
        "postal_code": "89502",
        "country": "US",
    }
    pickup_id, delivery_id = location_ids
    repo.update_location_ids_tx(
        shipment_row_id=upsert.shipment_id,
        pickup_location_id=pickup_id,
        delivery_location_id=delivery_id,
        delivery_address=delivery_address,
    )
    row = repo.get_by_tenant_and_shipment_number_tx(
        tenant_id=_TENANT_UUID,
        shipment_number=number,
    )
    assert row is not None
    assert row["delivery_address"]["city"] == "RENO"
    assert row["delivery_address"]["address1"] == "123 Main St"


@pytest.mark.skipif(not _db_available(), reason="DATABASE_URL unset or shipments migration missing")
def test_upsert_display_fields_coalesce_on_conflict(repo: ShipmentsRepository) -> None:
    number = f"test-{uuid.uuid4().hex[:12]}"
    first = repo.upsert_by_tenant_and_shipment_number_tx(
        tenant_id=_TENANT_UUID,
        shipment_number=number,
        metadata={"load_id": "LOAD-A"},
        carrier_name="Carrier A",
        customer_name="Customer A",
        delivery_date=date(2026, 4, 1),
    )
    assert first.created is True

    second = repo.upsert_by_tenant_and_shipment_number_tx(
        tenant_id=_TENANT_UUID,
        shipment_number=number,
        metadata={"load_id": "LOAD-B"},
        carrier_name=None,
        customer_name="Customer B",
        delivery_date=None,
    )
    assert second.created is False

    row = repo.get_by_tenant_and_shipment_number_tx(
        tenant_id=_TENANT_UUID,
        shipment_number=number,
    )
    assert row is not None
    assert row["carrier_name"] == "Carrier A"
    assert row["customer_name"] == "Customer B"
    assert row["delivery_date"] == date(2026, 4, 1)


def _any_two_location_ids() -> tuple[str, str] | None:
    try:
        with psycopg.connect(settings.DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id::text FROM locations ORDER BY id LIMIT 2")
                rows = cur.fetchall()
        if len(rows) < 2:
            return None
        return str(rows[0][0]), str(rows[1][0])
    except Exception:
        return None
