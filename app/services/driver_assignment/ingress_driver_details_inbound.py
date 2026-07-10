"""Inbound driver-details email ingress (delegates to T3RA email ingress service)."""

from __future__ import annotations

from typing import Any

from app.domain.ingress_result import IngressResult
from app.services.t3ra.driver_details_email_ingress import DriverDetailsEmailIngressService
from app.services.unipile_tenant_resolution import UnipileTenantContext


class IngressDriverDetailsInboundMixin:
    def _driver_details_email_ingress(self) -> DriverDetailsEmailIngressService:
        return DriverDetailsEmailIngressService(
            lifecycle_service=self._lifecycle_service,
            runs_service=self._runs_service,
            shipments_service=self._shipments,
            communications_service=self._communications,
            process_enabled_check=self._is_process_enabled,
        )

    def enqueue_driver_assignment_event_and_link(
        self,
        *,
        tenant_uuid: str,
        tenant_slug: str,
        workflow_lifecycle_id: str,
        payload: dict[str, Any],
        event_type: str,
        communication_id: str | None = None,
        thread_id: str | None = None,
    ) -> str:
        return self._driver_details_email_ingress().enqueue_driver_assignment_event_and_link(
            tenant_uuid=tenant_uuid,
            tenant_slug=tenant_slug,
            workflow_lifecycle_id=workflow_lifecycle_id,
            payload=payload,
            event_type=event_type,
            communication_id=communication_id,
            thread_id=thread_id,
        )

    def try_driver_details_email_received(
        self,
        *,
        payload: dict[str, Any],
        tenant: UnipileTenantContext,
        communication_id: str | None = None,
    ) -> IngressResult | None:
        return self._driver_details_email_ingress().try_driver_details_email_received(
            payload=payload,
            tenant=tenant,
            communication_id=communication_id,
        )
