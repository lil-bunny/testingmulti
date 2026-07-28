"""Reads/writes for ``shipments``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from sqlalchemy import text

from app.core.db import jsonb_param, parse_json

if TYPE_CHECKING:
    from sqlalchemy.orm import Session
    from datetime import datetime

_SELECT_SHIPMENT_COLUMNS = """
    id::text,
    shipment_number,
    metadata,
    delivery_address,
    pickup_date,
    pickup_timezone,
    delivery_date,
    delivery_timezone,
    carrier_name,
    customer_name,
    driver_details,
    proposed_pickup,
    proposed_delivery
"""


@dataclass(frozen=True)
class ShipmentUpsertResult:
    """``created`` is True when a new row was inserted; False on conflict update."""

    shipment_id: str
    created: bool


_WHERE_TENANT_SHIPMENT = """
    WHERE tenant_id = CAST(:tenant_id AS uuid) AND shipment_number = :shipment_number
"""


class ShipmentsRepository:
    TABLE_NAME = "shipments"

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def _clean(value: str | None) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _datetime_or_none(raw: Any) -> datetime | None:
        if raw is None:
            return None
        if hasattr(raw, "isoformat") and hasattr(raw, "tzinfo"):
            return raw
        return None

    @staticmethod
    def _row_to_dict(row: Any) -> dict[str, Any]:
        delivery_raw = row[3]
        if isinstance(delivery_raw, dict):
            delivery_address = delivery_raw
        elif delivery_raw in (None, ""):
            delivery_address = None
        else:
            delivery_address = parse_json(delivery_raw)
            if not delivery_address:
                delivery_address = None

        driver_details_raw = row[10]
        if isinstance(driver_details_raw, dict):
            driver_details = driver_details_raw
        elif driver_details_raw in (None, ""):
            driver_details = None
        else:
            driver_details = parse_json(driver_details_raw)
            if not driver_details:
                driver_details = None

        return {
            "id": str(row[0]),
            "shipment_number": row[1] or "",
            "metadata": parse_json(row[2]),
            "delivery_address": delivery_address,
            "pickup_date": ShipmentsRepository._datetime_or_none(row[4]),
            "pickup_timezone": row[5] or None,
            "delivery_date": ShipmentsRepository._datetime_or_none(row[6]),
            "delivery_timezone": row[7] or None,
            "carrier_name": row[8] or None,
            "customer_name": row[9] or None,
            "driver_details": driver_details,
            "proposed_pickup": ShipmentsRepository._datetime_or_none(row[11]),
            "proposed_delivery": ShipmentsRepository._datetime_or_none(row[12]),
        }

    def upsert_by_tenant_and_shipment_number_tx(
        self,
        *,
        tenant_id: str,
        shipment_number: str,
        metadata: dict[str, Any],
        pickup_date: datetime | None = None,
        pickup_timezone: str | None = None,
        delivery_date: datetime | None = None,
        delivery_timezone: str | None = None,
        carrier_name: str | None = None,
        customer_name: str | None = None,
    ) -> ShipmentUpsertResult:
        tid = self._clean(tenant_id)
        number = self._clean(shipment_number)
        if not tid or not number:
            raise ValueError("tenant_id and shipment_number are required")

        row = self._session.execute(
            text(
                f"""
                INSERT INTO {self.TABLE_NAME} (
                    tenant_id,
                    shipment_number,
                    metadata,
                    pickup_date,
                    pickup_timezone,
                    delivery_date,
                    delivery_timezone,
                    carrier_name,
                    customer_name
                ) VALUES (
                    CAST(:tenant_id AS uuid),
                    :shipment_number,
                    CAST(:metadata AS jsonb),
                    :pickup_date,
                    :pickup_timezone,
                    :delivery_date,
                    :delivery_timezone,
                    :carrier_name,
                    :customer_name
                )
                ON CONFLICT (tenant_id, shipment_number)
                DO UPDATE SET
                    updated_at = NOW(),
                    metadata = {self.TABLE_NAME}.metadata || EXCLUDED.metadata,
                    pickup_date = COALESCE(
                        EXCLUDED.pickup_date,
                        {self.TABLE_NAME}.pickup_date
                    ),
                    pickup_timezone = COALESCE(
                        EXCLUDED.pickup_timezone,
                        {self.TABLE_NAME}.pickup_timezone
                    ),
                    delivery_date = COALESCE(
                        EXCLUDED.delivery_date,
                        {self.TABLE_NAME}.delivery_date
                    ),
                    delivery_timezone = COALESCE(
                        EXCLUDED.delivery_timezone,
                        {self.TABLE_NAME}.delivery_timezone
                    ),
                    carrier_name = COALESCE(
                        EXCLUDED.carrier_name,
                        {self.TABLE_NAME}.carrier_name
                    ),
                    customer_name = COALESCE(
                        EXCLUDED.customer_name,
                        {self.TABLE_NAME}.customer_name
                    )
                RETURNING id::text, (xmax = 0) AS created
                """
            ),
            {
                "tenant_id": tid,
                "shipment_number": number,
                "metadata": jsonb_param(metadata),
                "pickup_date": pickup_date,
                "pickup_timezone": self._clean(pickup_timezone),
                "delivery_date": delivery_date,
                "delivery_timezone": self._clean(delivery_timezone),
                "carrier_name": self._clean(carrier_name),
                "customer_name": self._clean(customer_name),
            },
        ).first()
        if not row or not row[0]:
            raise RuntimeError("shipments upsert returned no row")
        return ShipmentUpsertResult(
            shipment_id=str(row[0]),
            created=bool(row[1]),
        )

    def get_by_tenant_and_shipment_number_tx(
        self,
        *,
        tenant_id: str,
        shipment_number: str,
    ) -> dict[str, Any] | None:
        tid = self._clean(tenant_id)
        number = self._clean(shipment_number)
        if not tid or not number:
            return None

        row = self._session.execute(
            text(
                f"""
                SELECT {_SELECT_SHIPMENT_COLUMNS}
                FROM {self.TABLE_NAME}
                {_WHERE_TENANT_SHIPMENT}
                LIMIT 1
                """
            ),
            {"tenant_id": tid, "shipment_number": number},
        ).first()
        if not row:
            return None

        return self._row_to_dict(row)

    def get_by_tenant_and_id_tx(
        self,
        *,
        tenant_id: str,
        shipment_id: str,
    ) -> dict[str, Any] | None:
        tid = self._clean(tenant_id)
        sid = self._clean(shipment_id)
        if not tid or not sid:
            return None

        row = self._session.execute(
            text(
                f"""
                SELECT {_SELECT_SHIPMENT_COLUMNS}
                FROM {self.TABLE_NAME}
                WHERE id = CAST(:shipment_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                LIMIT 1
                """
            ),
            {"tenant_id": tid, "shipment_id": sid},
        ).first()
        if not row:
            return None

        return self._row_to_dict(row)

    def update_location_ids_tx(
        self,
        *,
        shipment_row_id: str,
        pickup_location_id: str,
        delivery_location_id: str,
        delivery_address: dict[str, Any] | None = None,
    ) -> None:
        row_id = self._clean(shipment_row_id)
        pickup_id = self._clean(pickup_location_id)
        delivery_id = self._clean(delivery_location_id)
        if not row_id or not pickup_id or not delivery_id:
            raise ValueError(
                "shipment_row_id, pickup_location_id, and delivery_location_id are required"
            )

        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET pickup_location_id = CAST(:pickup_location_id AS uuid),
                    delivery_location_id = CAST(:delivery_location_id AS uuid),
                    delivery_address = CAST(:delivery_address AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:shipment_row_id AS uuid)
                """
            ),
            {
                "pickup_location_id": pickup_id,
                "delivery_location_id": delivery_id,
                "delivery_address": jsonb_param(delivery_address),
                "shipment_row_id": row_id,
            },
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"shipments location update affected {result.rowcount} rows"
            )

    def merge_driver_details_tx(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
        driver_details: dict[str, Any],
    ) -> None:
        tid = self._clean(tenant_id)
        row_id = self._clean(shipment_row_id)
        if not tid or not row_id:
            raise ValueError("tenant_id and shipment_row_id are required")

        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET driver_details = CAST(:driver_details AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:shipment_row_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {
                "tenant_id": tid,
                "shipment_row_id": row_id,
                "driver_details": jsonb_param(driver_details),
            },
        )
        if result.rowcount != 1:
            raise RuntimeError(
                f"shipments driver_details update affected {result.rowcount} rows"
            )

    def merge_metadata_by_id_tx(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
        metadata_patch: dict[str, Any],
    ) -> bool:
        """Merge ``metadata_patch`` into ``shipments.metadata`` (tenant-scoped)."""
        tid = self._clean(tenant_id)
        row_id = self._clean(shipment_row_id)
        if not tid or not row_id or not metadata_patch:
            return False

        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET metadata = COALESCE(metadata, '{{}}'::jsonb)
                    || CAST(:metadata_patch AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:shipment_row_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {
                "tenant_id": tid,
                "shipment_row_id": row_id,
                "metadata_patch": jsonb_param(metadata_patch),
            },
        )
        return result.rowcount == 1

    def update_proposed_appointments_tx(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
        proposed_pickup: datetime | None = None,
        proposed_delivery: datetime | None = None,
    ) -> bool:
        """Set ``shipments.proposed_*``; COALESCE keeps existing value when arg is None."""
        tid = self._clean(tenant_id)
        row_id = self._clean(shipment_row_id)
        if not tid or not row_id:
            return False
        if proposed_pickup is None and proposed_delivery is None:
            return False

        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET proposed_pickup = COALESCE(
                        CAST(:proposed_pickup AS timestamptz),
                        proposed_pickup
                    ),
                    proposed_delivery = COALESCE(
                        CAST(:proposed_delivery AS timestamptz),
                        proposed_delivery
                    ),
                    updated_at = NOW()
                WHERE id = CAST(:shipment_row_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {
                "tenant_id": tid,
                "shipment_row_id": row_id,
                "proposed_pickup": proposed_pickup,
                "proposed_delivery": proposed_delivery,
            },
        )
        return result.rowcount == 1

    def clear_driver_details_tx(
        self,
        *,
        tenant_id: str,
        shipment_row_id: str,
    ) -> bool:
        tid = self._clean(tenant_id)
        row_id = self._clean(shipment_row_id)
        if not tid or not row_id:
            raise ValueError("tenant_id and shipment_row_id are required")

        empty_driver_details = {"name": None, "phone": None}
        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET driver_details = CAST(:driver_details AS jsonb),
                    updated_at = NOW()
                WHERE id = CAST(:shipment_row_id AS uuid)
                  AND tenant_id = CAST(:tenant_id AS uuid)
                """
            ),
            {
                "tenant_id": tid,
                "shipment_row_id": row_id,
                "driver_details": jsonb_param(empty_driver_details),
            },
        )
        return result.rowcount == 1
