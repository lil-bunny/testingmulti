"""Resolve driver contacts in TMS and assign to shipment."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from app.core.logger import get_logger
from app.integrations.turvo.contacts import (
    create_driver_contact,
    search_carrier_driver_contacts,
)
from app.integrations.turvo.ui_accounts import (
    search_carrier_driver_contacts_by_name,
    search_carrier_driver_contacts_by_phone,
)
from app.integrations.turvo.public_api_client import TurvoApiError
from app.integrations.turvo.shipments import (
    assign_driver_to_shipment,
    carrier_from_order,
    customer_name_from_payload,
    driver_assigned_from_payload,
    first_active_carrier_order,
    get_shipment,
    segment_id_from_order,
)
from app.domain.driver_assignment.confirmation_email import (
    parse_driver_assignment_confirmation_email,
)
from app.models.tenants import TenantSlug
from app.domain.tenant_settings.workflow_shadow_mode import workflow_shadow_active
from app.tools.driver_details import (
    can_create_tms_driver_contact,
    contact_row_name_phone,
    driver_block_name_phone,
    is_tms_tracking_customer,
    name_tokens_match,
    normalize_phone_digits,
    pick_phone_duplicate_contact,
)

logger = get_logger(__name__)

TmsDriverOutcome = Literal["assigned", "follow_up", "error"]
TmsResolution = Literal[
    "found",
    "not_found",
    "ambiguous",
    "created",
    "assigned",
    "skipped_already_assigned",
    "failed",
]


@dataclass
class TmsDriverResolution:
    outcome: TmsDriverOutcome
    tms_resolution: TmsResolution
    tms_shipment_id: str | None = None
    tms_carrier_id: int | None = None
    tms_contact_id: int | None = None
    tms_match_count: int | None = None
    tms_search_match_by: str | None = None
    tms_follow_up_reason: str | None = None
    tms_driver_error: str | None = None
    tms_contact_created: bool = False
    tms_customer_name: str | None = None
    tms_is_tracking_customer: bool = False
    tms_matched_driver_name: str | None = None
    tms_matched_driver_phone: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        patch: dict[str, Any] = {
            "tms_driver_outcome": self.outcome,
            "tms_resolution": self.tms_resolution,
        }
        for key in (
            "tms_shipment_id",
            "tms_carrier_id",
            "tms_contact_id",
            "tms_match_count",
            "tms_search_match_by",
            "tms_follow_up_reason",
            "tms_driver_error",
        ):
            val = getattr(self, key)
            if val is not None:
                patch[key] = val
        if self.tms_contact_created:
            patch["tms_contact_created"] = True
        if self.tms_customer_name:
            patch["tms_customer_name"] = self.tms_customer_name
        if self.tms_is_tracking_customer:
            patch["tms_is_tracking_customer"] = True
        if self.tms_matched_driver_name:
            patch["tms_matched_driver_name"] = self.tms_matched_driver_name
        if self.tms_matched_driver_phone:
            patch["tms_matched_driver_phone"] = self.tms_matched_driver_phone
        return patch


class DriverAssignmentTurvoService:
    def resolve_from_state(self, state) -> dict[str, Any]:
        """Workflow entry: read state, call TMS, return state patch (sync for nodes)."""
        import asyncio

        tenant_slug = (
            (getattr(state, "data", {}) or {}).get("tenant_slug") or ""
        ).strip() or TenantSlug.T3RA.value
        shipment_id = str((state.data or {}).get("shipment_id") or "").strip()
        extraction = (state.data or {}).get("driver_details_extraction") or {}
        driver = extraction.get("driver") if isinstance(extraction, dict) else {}
        if not isinstance(driver, dict):
            driver = {}
        result = asyncio.run(
            self.resolve_and_assign(
                tenant_slug=tenant_slug,
                shipment_id=shipment_id,
                driver=driver,
                tenant_settings=(state.data or {}).get("tenant_settings"),
                state_data=state.data or {},
            )
        )
        patch = result.to_state_patch()
        if result.outcome == "assigned" and (
            result.tms_matched_driver_name or result.tms_matched_driver_phone
        ):
            merged_extraction = dict(extraction) if isinstance(extraction, dict) else {}
            merged_driver = dict(driver)
            if result.tms_matched_driver_name:
                merged_driver["name"] = result.tms_matched_driver_name
            if result.tms_matched_driver_phone:
                merged_driver["phone"] = result.tms_matched_driver_phone
            merged_extraction["driver"] = merged_driver
            patch["driver_details_extraction"] = merged_extraction
        return patch

    async def resolve_and_assign(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
        driver: dict[str, str | None],
        tenant_settings: dict[str, Any] | None = None,
        state_data: dict[str, Any] | None = None,
    ) -> TmsDriverResolution:
        slug = (tenant_slug or "").strip()
        sid = str(shipment_id or "").strip()
        name = (driver.get("name") or "").strip() or None
        phone = (driver.get("phone") or "").strip() or None
        email = (driver.get("email") or "").strip() or None
        shadow = workflow_shadow_active(
            tenant_settings if isinstance(tenant_settings, dict) else None,
            state_data,
            workflow_name="driver_assignment",
        )

        if not slug or not sid:
            return TmsDriverResolution(
                outcome="error",
                tms_resolution="failed",
                tms_driver_error="missing_tenant_or_shipment",
            )

        try:
            shipment = await get_shipment(slug, sid)
        except TurvoApiError as e:
            logger.warning("TMS get_shipment failed shipment_id=%s status=%s", sid, e.status_code)
            return TmsDriverResolution(
                outcome="error",
                tms_resolution="failed",
                tms_shipment_id=sid,
                tms_driver_error="tms_shipment_fetch_failed",
            )

        customer_name = customer_name_from_payload(shipment)
        conf = parse_driver_assignment_confirmation_email(
            tenant_settings if isinstance(tenant_settings, dict) else None
        )
        tracking_names = conf.tracking_customer_name_set if conf else frozenset()
        is_tracking = is_tms_tracking_customer(
            customer_name,
            tracking_customer_names=tracking_names,
        )
        send_invite = (
            conf.send_invite_for(is_tracking_customer=is_tracking)
            if conf
            else not is_tracking
        )

        if driver_assigned_from_payload(shipment):
            order = first_active_carrier_order(shipment) or {}
            carrier_id, _ = carrier_from_order(order)
            return TmsDriverResolution(
                outcome="assigned",
                tms_resolution="skipped_already_assigned",
                tms_shipment_id=sid,
                tms_carrier_id=carrier_id,
                tms_customer_name=customer_name,
                tms_is_tracking_customer=is_tracking,
            )

        order = first_active_carrier_order(shipment)
        if not order:
            return TmsDriverResolution(
                outcome="follow_up",
                tms_resolution="not_found",
                tms_shipment_id=sid,
                tms_follow_up_reason="missing_carrier",
            )

        carrier_id, carrier_name = carrier_from_order(order)
        carrier_order_id = order.get("id")
        segment_id = segment_id_from_order(order)
        if not carrier_id or not carrier_name or not carrier_order_id:
            return TmsDriverResolution(
                outcome="follow_up",
                tms_resolution="not_found",
                tms_shipment_id=sid,
                tms_carrier_id=carrier_id,
                tms_follow_up_reason="missing_carrier",
            )

        try:
            contact_id, resolution = await self._resolve_contact_id(
                slug,
                driver={"name": name, "phone": phone, "email": email},
                carrier_id=carrier_id,
                carrier_name=carrier_name,
                shipment_payload=shipment,
                shadow=shadow,
            )
        except TurvoApiError as e:
            logger.warning(
                "TMS contact resolve failed shipment_id=%s status=%s",
                sid,
                e.status_code,
            )
            return TmsDriverResolution(
                outcome="error",
                tms_resolution="failed",
                tms_shipment_id=sid,
                tms_carrier_id=carrier_id,
                tms_driver_error="tms_contact_resolve_failed",
            )

        if contact_id is None:
            if (
                shadow
                and resolution.tms_resolution == "not_found"
                and can_create_tms_driver_contact(driver)
            ):
                matched_name, matched_phone = driver_block_name_phone(driver)
                return TmsDriverResolution(
                    outcome="assigned",
                    tms_resolution="created",
                    tms_contact_created=True,
                    tms_shipment_id=sid,
                    tms_carrier_id=carrier_id,
                    tms_matched_driver_name=matched_name,
                    tms_matched_driver_phone=matched_phone,
                    tms_customer_name=customer_name,
                    tms_is_tracking_customer=is_tracking,
                )
            return resolution  # type: ignore[return-value]

        if shadow:
            logger.info(
                "shadow_mode skipped TMS assign driver shipment_id=%s contact_id=%s",
                sid,
                contact_id,
            )
            return TmsDriverResolution(
                outcome="assigned",
                tms_resolution=(
                    "created"
                    if resolution.tms_contact_created
                    else ("found" if resolution.tms_resolution == "found" else "assigned")
                ),
                tms_shipment_id=sid,
                tms_carrier_id=carrier_id,
                tms_contact_id=contact_id,
                tms_match_count=resolution.tms_match_count,
                tms_search_match_by=resolution.tms_search_match_by,
                tms_contact_created=resolution.tms_contact_created,
                tms_customer_name=customer_name,
                tms_is_tracking_customer=is_tracking,
                tms_matched_driver_name=resolution.tms_matched_driver_name,
                tms_matched_driver_phone=resolution.tms_matched_driver_phone,
            )

        try:
            await assign_driver_to_shipment(
                slug,
                sid,
                carrier_order_id=int(carrier_order_id),
                contact_id=contact_id,
                segment_id=segment_id,
                send_invite=send_invite,
            )
        except TurvoApiError as e:
            logger.warning(
                "TMS assign driver failed shipment_id=%s contact_id=%s status=%s",
                sid,
                contact_id,
                e.status_code,
            )
            return TmsDriverResolution(
                outcome="error",
                tms_resolution="failed",
                tms_shipment_id=sid,
                tms_carrier_id=carrier_id,
                tms_contact_id=contact_id,
                tms_driver_error="tms_assign_failed",
            )

        return TmsDriverResolution(
            outcome="assigned",
            tms_resolution=(
                "created"
                if resolution.tms_contact_created
                else ("found" if resolution.tms_resolution == "found" else "assigned")
            ),
            tms_shipment_id=sid,
            tms_carrier_id=carrier_id,
            tms_contact_id=contact_id,
            tms_match_count=resolution.tms_match_count,
            tms_search_match_by=resolution.tms_search_match_by,
            tms_contact_created=resolution.tms_contact_created,
            tms_customer_name=customer_name,
            tms_is_tracking_customer=is_tracking,
            tms_matched_driver_name=resolution.tms_matched_driver_name,
            tms_matched_driver_phone=resolution.tms_matched_driver_phone,
        )

    async def _resolve_contact_id(
        self,
        tenant_slug: str,
        *,
        driver: dict[str, str | None],
        carrier_id: int,
        carrier_name: str,
        shipment_payload: dict[str, Any] | None = None,
        shadow: bool = False,
    ) -> tuple[int | None, TmsDriverResolution]:
        name = driver.get("name")
        phone = driver.get("phone")
        email = driver.get("email")
        has_phone = bool(normalize_phone_digits(phone))
        has_name = bool(name)
        has_email = bool(email)

        if has_phone:
            phone_matches = await self._search_by_phone(
                tenant_slug,
                phone=phone,
                name=None,
                carrier_id=carrier_id,
                carrier_name=carrier_name,
                shipment_payload=shipment_payload,
            )
            match_by = "name_and_phone" if has_name else "phone"
            phone_count = len(phone_matches)

            if phone_count == 1:
                return self._pick_only(
                    matches=phone_matches,
                    match_by=match_by,
                    driver=driver,
                    carrier_id=carrier_id,
                )

            if phone_count == 0:
                if has_name:
                    return await self._pick_or_create(
                        tenant_slug,
                        matches=phone_matches,
                        driver=driver,
                        match_by=match_by,
                        carrier_id=carrier_id,
                        carrier_name=carrier_name,
                        allow_create=True,
                        shadow=shadow,
                    )
                return self._pick_only(
                    matches=phone_matches,
                    match_by=match_by,
                    driver=driver,
                    carrier_id=carrier_id,
                )

            candidates = (
                self._narrow_matches_by_name(phone_matches, name)
                if has_name
                else phone_matches
            )
            if has_name and not candidates:
                return None, TmsDriverResolution(
                    outcome="follow_up",
                    tms_resolution="not_found",
                    tms_follow_up_reason="not_found",
                    tms_match_count=0,
                    tms_search_match_by=match_by,
                    tms_carrier_id=carrier_id,
                )
            if len(candidates) > 1:
                picked = pick_phone_duplicate_contact(candidates)
                if picked is not None:
                    return self._pick_only(
                        matches=[picked],
                        match_by=match_by,
                        driver=driver,
                        carrier_id=carrier_id,
                    )
            return self._pick_only(
                matches=candidates,
                match_by=match_by,
                driver=driver,
                carrier_id=carrier_id,
            )

        if has_name:
            matches = await self._search_by_name(
                tenant_slug,
                name=name,
                carrier_id=carrier_id,
                carrier_name=carrier_name,
                shipment_payload=shipment_payload,
            )
            return self._pick_only(
                matches=matches,
                match_by="name",
                driver=driver,
                carrier_id=carrier_id,
            )

        if has_email:
            matches = await self._search_by_email(
                tenant_slug,
                email=email,
                carrier_id=carrier_id,
                carrier_name=carrier_name,
                shipment_payload=shipment_payload,
            )
            return await self._pick_or_create(
                tenant_slug,
                matches=matches,
                driver=driver,
                match_by="email",
                carrier_id=carrier_id,
                carrier_name=carrier_name,
                allow_create=can_create_tms_driver_contact(driver),
                shadow=shadow,
            )

        return None, TmsDriverResolution(
            outcome="follow_up",
            tms_resolution="not_found",
            tms_carrier_id=carrier_id,
            tms_follow_up_reason="not_found",
        )

    async def _search_by_name(
        self,
        tenant_slug: str,
        *,
        name: str,
        carrier_id: int,
        carrier_name: str,
        shipment_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        matches = await search_carrier_driver_contacts(
            tenant_slug,
            carrier_id=carrier_id,
            carrier_name=carrier_name,
            name=name,
            shipment_payload=shipment_payload,
        )
        if not matches:
            matches = await search_carrier_driver_contacts_by_name(
                tenant_slug,
                carrier_id=carrier_id,
                carrier_name=carrier_name,
                name=name,
            )
        return matches

    async def _search_by_email(
        self,
        tenant_slug: str,
        *,
        email: str,
        carrier_id: int,
        carrier_name: str,
        shipment_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        return await search_carrier_driver_contacts(
            tenant_slug,
            carrier_id=carrier_id,
            carrier_name=carrier_name,
            email=email,
            shipment_payload=shipment_payload,
        )

    async def _search_by_phone(
        self,
        tenant_slug: str,
        *,
        phone: str,
        name: str | None,
        carrier_id: int,
        carrier_name: str,
        shipment_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        _ = shipment_payload
        return await search_carrier_driver_contacts_by_phone(
            tenant_slug,
            carrier_id=carrier_id,
            carrier_name=carrier_name,
            phone=phone,
            name=name,
        )

    @staticmethod
    def _narrow_matches_by_name(
        matches: list[dict[str, Any]],
        name: str | None,
    ) -> list[dict[str, Any]]:
        cleaned = str(name or "").strip()
        if not cleaned:
            return matches
        return [
            row for row in matches if name_tokens_match(cleaned, row.get("name"))
        ]

    def _pick_only(
        self,
        *,
        matches: list[dict[str, Any]],
        match_by: str,
        driver: dict[str, str | None],
        carrier_id: int,
    ) -> tuple[int | None, TmsDriverResolution]:
        count = len(matches)
        base = dict(
            tms_match_count=count,
            tms_search_match_by=match_by,
            tms_carrier_id=carrier_id,
        )
        if count == 0:
            return None, TmsDriverResolution(
                outcome="follow_up",
                tms_resolution="not_found",
                tms_follow_up_reason="not_found",
                **base,
            )
        if count == 1:
            matched_name, matched_phone = contact_row_name_phone(matches[0])
            return int(matches[0]["id"]), TmsDriverResolution(
                outcome="assigned",
                tms_resolution="found",
                tms_matched_driver_name=matched_name,
                tms_matched_driver_phone=matched_phone,
                **base,
            )
        return None, TmsDriverResolution(
            outcome="follow_up",
            tms_resolution="ambiguous",
            tms_follow_up_reason="multiple_matches",
            **base,
        )

    async def _pick_or_create(
        self,
        tenant_slug: str,
        *,
        matches: list[dict[str, Any]],
        driver: dict[str, str | None],
        match_by: str,
        carrier_id: int,
        carrier_name: str,
        allow_create: bool,
        shadow: bool = False,
    ) -> tuple[int | None, TmsDriverResolution]:
        count = len(matches)
        base = dict(
            tms_match_count=count,
            tms_search_match_by=match_by,
            tms_carrier_id=carrier_id,
        )
        if count == 1:
            matched_name, matched_phone = contact_row_name_phone(matches[0])
            return int(matches[0]["id"]), TmsDriverResolution(
                outcome="assigned",
                tms_resolution="found",
                tms_matched_driver_name=matched_name,
                tms_matched_driver_phone=matched_phone,
                **base,
            )
        if count > 1:
            return None, TmsDriverResolution(
                outcome="follow_up",
                tms_resolution="ambiguous",
                tms_follow_up_reason="multiple_matches",
                **base,
            )
        if not allow_create:
            return None, TmsDriverResolution(
                outcome="follow_up",
                tms_resolution="not_found",
                tms_follow_up_reason="not_found",
                **base,
            )
        if shadow:
            return None, TmsDriverResolution(
                outcome="follow_up",
                tms_resolution="not_found",
                tms_follow_up_reason="not_found",
                **base,
            )
        name = (driver.get("name") or "").strip()
        email = (driver.get("email") or "").strip() or None
        contact_id = await create_driver_contact(
            tenant_slug,
            name=name,
            phone=driver.get("phone"),
            email=email,
            carrier_id=carrier_id,
            carrier_name=carrier_name,
        )
        matched_name, matched_phone = driver_block_name_phone(driver)
        return contact_id, TmsDriverResolution(
            outcome="assigned",
            tms_resolution="created",
            tms_contact_created=True,
            tms_contact_id=contact_id,
            tms_match_count=0,
            tms_search_match_by=match_by,
            tms_carrier_id=carrier_id,
            tms_matched_driver_name=matched_name,
            tms_matched_driver_phone=matched_phone,
        )
