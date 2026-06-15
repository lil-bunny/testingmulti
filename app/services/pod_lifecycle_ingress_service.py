"""Pre-graph ingress for ``pod_lifecycle`` (route_completed dedupe + email_received correlation)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.pod_lifecycle_guards import is_pod_processing_complete_sub_status
from app.domain.ratecon_import import (
    attachment_display_filename,
    is_pdf_attachment,
    load_id_from_ratecon_attachment_name,
)
from app.domain.status_parsing import sub_status_type_from_db
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.services.communications.service import CommunicationsService
from app.services.shipments_service import ShipmentsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.services.workflow_runs_service import WorkflowRunsService

logger = get_logger(__name__)

POD_LIFECYCLE_WORKFLOW = "pod_lifecycle"


@dataclass(frozen=True)
class RouteCompletedDuplicateResult:
    is_duplicate: bool
    lifecycle_id: str | None = None
    shipments_row_id: str | None = None


@dataclass(frozen=True)
class PodEmailReceivedResolution:
    shipments_row_id: str
    shipment_number: str
    workflow_lifecycle_id: str | None
    resolution_source: str


class PodLifecycleIngressService:
    """Ingress checks and payload enrichment before ``pod_lifecycle`` graph runs."""

    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        runs_service: WorkflowRunsService | None = None,
        shipments_service: ShipmentsService | None = None,
        communications_service: CommunicationsService | None = None,
    ) -> None:
        self._lifecycle_service = lifecycle_service or WorkflowLifecycleService()
        self._runs_service = runs_service or WorkflowRunsService()
        self._shipments = shipments_service or ShipmentsService()
        self._communications = communications_service or CommunicationsService()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    def _resolve_shipments_row_id(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> str | None:
        row_id = self._clean(payload.get("shipments_row_id"))
        if row_id:
            return row_id

        external = self._clean(payload.get("shipment_id"))
        if not external:
            return None

        row = self._shipments.get_by_shipment_number(
            tenant_id=tenant_id,
            shipment_number=external,
        )
        if not row:
            return None
        return self._clean(row.get("id"))

    def _shipment_number_for_row(
        self,
        *,
        tenant_id: str,
        shipments_row_id: str,
        payload: dict[str, Any],
    ) -> str | None:
        external = self._clean(payload.get("shipment_id"))
        row = self._shipments.get_by_id(
            tenant_id=tenant_id,
            shipment_id=shipments_row_id,
        )
        if row:
            number = self._clean(row.get("shipment_number"))
            if number:
                return number
        return external

    @staticmethod
    def _load_id_from_attachments(payload: dict[str, Any]) -> str | None:
        attachments = payload.get("attachments")
        if not isinstance(attachments, list):
            return None
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            name = attachment_display_filename(attachment)
            if not name or not is_pdf_attachment(attachment, name):
                continue
            load_id = load_id_from_ratecon_attachment_name(name)
            if load_id:
                return load_id
        return None

    def _pod_lifecycle_id_for_shipment(
        self,
        *,
        tenant_id: str,
        shipments_row_id: str,
    ) -> str | None:
        lifecycle = self._lifecycle_service.check_lifecycle_exists(
            tenant_id=tenant_id,
            workflow_name=POD_LIFECYCLE_WORKFLOW,
            shipment_id=shipments_row_id,
        )
        if not lifecycle.get("exists"):
            return None
        return self._clean(lifecycle.get("lifecycle_id"))

    def _pick_thread_context(
        self,
        rows: list[dict[str, Any]],
    ) -> tuple[str, str, str | None] | None:
        if not rows:
            return None

        distinct_shipments = {
            self._clean(r.get("shipments_row_id"))
            for r in rows
            if self._clean(r.get("shipments_row_id"))
        }
        if len(distinct_shipments) > 1:
            logger.warning(
                "pod email ingress: multiple shipments on thread shipments=%s",
                sorted(distinct_shipments),
            )

        primary = rows[0]
        shipments_row_id = self._clean(primary.get("shipments_row_id"))
        shipment_number = self._clean(primary.get("shipment_number"))
        if not shipments_row_id or not shipment_number:
            return None

        pod_lifecycle_id: str | None = None
        for row in rows:
            if self._clean(row.get("shipments_row_id")) != shipments_row_id:
                continue
            if self._clean(row.get("workflow_name")) == POD_LIFECYCLE_WORKFLOW:
                pod_lifecycle_id = self._clean(row.get("lifecycle_id"))
                break

        return shipments_row_id, shipment_number, pod_lifecycle_id

    def _apply_resolution(
        self,
        payload: dict[str, Any],
        *,
        tenant_id: str,
        resolution: PodEmailReceivedResolution,
    ) -> dict[str, Any]:
        out = dict(payload)
        out["shipments_row_id"] = resolution.shipments_row_id
        out["shipment_id"] = resolution.shipment_number
        if resolution.workflow_lifecycle_id:
            out["workflow_lifecycle_id"] = resolution.workflow_lifecycle_id
        logger.info(
            "pod email ingress resolved tenant_id=%s thread_id=%s source=%s "
            "shipments_row_id=%s shipment_id=%s workflow_lifecycle_id=%s",
            tenant_id,
            self._clean(payload.get("thread_id")),
            resolution.resolution_source,
            resolution.shipments_row_id,
            resolution.shipment_number,
            resolution.workflow_lifecycle_id,
        )
        return out

    async def prepare_email_received_payload(
        self,
        *,
        tenant_id: str,
        tenant_slug: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Resolve shipment + optional existing pod lifecycle before graph correlation.

        Mirrors manual upload keys: ``shipments_row_id``, Turvo ``shipment_id``,
        and ``workflow_lifecycle_id`` when a pod lifecycle already exists.
        """
        tid = self._clean(tenant_id)
        if not tid:
            raise Exception("pod_lifecycle email_received: missing tenant_id")

        existing_row_id = self._resolve_shipments_row_id(tenant_id=tid, payload=payload)
        if existing_row_id:
            shipment_number = self._shipment_number_for_row(
                tenant_id=tid,
                shipments_row_id=existing_row_id,
                payload=payload,
            )
            if not shipment_number:
                raise Exception(
                    "pod_lifecycle email_received: could not resolve Turvo shipment_number "
                    f"for shipments_row_id={existing_row_id!r}"
                )
            pod_lc_id = self._pod_lifecycle_id_for_shipment(
                tenant_id=tid,
                shipments_row_id=existing_row_id,
            )
            return self._apply_resolution(
                payload,
                tenant_id=tid,
                resolution=PodEmailReceivedResolution(
                    shipments_row_id=existing_row_id,
                    shipment_number=shipment_number,
                    workflow_lifecycle_id=pod_lc_id,
                    resolution_source="payload",
                ),
            )

        thread_id = self._clean(payload.get("thread_id"))
        if thread_id:
            rows = self._communications.find_shipment_context_for_thread(
                tenant_id=tid,
                thread_id=thread_id,
            )
            picked = self._pick_thread_context(rows)
            if picked:
                shipments_row_id, shipment_number, pod_lc_id = picked
                if not pod_lc_id:
                    pod_lc_id = self._pod_lifecycle_id_for_shipment(
                        tenant_id=tid,
                        shipments_row_id=shipments_row_id,
                    )
                return self._apply_resolution(
                    payload,
                    tenant_id=tid,
                    resolution=PodEmailReceivedResolution(
                        shipments_row_id=shipments_row_id,
                        shipment_number=shipment_number,
                        workflow_lifecycle_id=pod_lc_id,
                        resolution_source="thread",
                    ),
                )

        load_id = self._load_id_from_attachments(payload)
        if load_id:
            persist = await self._shipments.upsert_from_load_id(
                tenant_id=tid,
                tenant_slug=tenant_slug,
                load_id=load_id,
            )
            if not persist.get("success") or not persist.get("shipments_row_id"):
                message = persist.get("message") or "shipments_upsert_failed"
                if message == "turvo_load_resolve_failed":
                    raise Exception(
                        f"pod_lifecycle email_received: Turvo load resolve failed: {message}"
                    )
                if message == "turvo_shipment_not_found":
                    raise Exception(
                        "pod_lifecycle email_received: Turvo load resolve failed: "
                        f"no shipment for load_id={load_id!r}"
                    )
                raise Exception(
                    f"pod_lifecycle email_received: shipment upsert failed: {message}"
                )

            turvo_shipment_id = str(persist.get("shipment_number") or "").strip()

            shipments_row_id = str(persist["shipments_row_id"])
            pod_lc_id = self._pod_lifecycle_id_for_shipment(
                tenant_id=tid,
                shipments_row_id=shipments_row_id,
            )
            return self._apply_resolution(
                payload,
                tenant_id=tid,
                resolution=PodEmailReceivedResolution(
                    shipments_row_id=shipments_row_id,
                    shipment_number=turvo_shipment_id,
                    workflow_lifecycle_id=pod_lc_id,
                    resolution_source="attachment_load_id",
                ),
            )

        raise Exception(
            "pod_lifecycle email_received: could not resolve shipment "
            f"(tenant_id={tid!r} thread_id={thread_id!r})"
        )

    def check_route_completed_duplicate(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> RouteCompletedDuplicateResult:
        """
        Return whether this ``route_completed`` payload is a duplicate.

        Uses read-only lifecycle lookup (no row creation) then ``workflow_runs``.
        """
        event_type = self._clean(payload.get("event_type"))
        if event_type != WorkflowRunEventType.ROUTE_COMPLETED.value:
            return RouteCompletedDuplicateResult(is_duplicate=False)

        tid = self._clean(tenant_id)
        if not tid:
            return RouteCompletedDuplicateResult(is_duplicate=False)

        shipments_row_id = self._resolve_shipments_row_id(
            tenant_id=tid,
            payload=payload,
        )
        if not shipments_row_id:
            return RouteCompletedDuplicateResult(is_duplicate=False)

        lifecycle = self._lifecycle_service.check_lifecycle_exists(
            tenant_id=tid,
            workflow_name=POD_LIFECYCLE_WORKFLOW,
            shipment_id=shipments_row_id,
        )
        if not lifecycle.get("exists"):
            return RouteCompletedDuplicateResult(
                is_duplicate=False,
                shipments_row_id=shipments_row_id,
            )

        lifecycle_id = self._clean(lifecycle.get("lifecycle_id"))
        if not lifecycle_id:
            return RouteCompletedDuplicateResult(
                is_duplicate=False,
                shipments_row_id=shipments_row_id,
            )

        blocked = self._runs_service.is_workflow_initial_path_blocked(
            tenant_id=tid,
            event_type=WorkflowRunEventType.ROUTE_COMPLETED.value,
            workflow_lifecycle_id=lifecycle_id,
            shipment_id=shipments_row_id,
            exclude_run_id=None,
        )
        return RouteCompletedDuplicateResult(
            is_duplicate=blocked,
            lifecycle_id=lifecycle_id,
            shipments_row_id=shipments_row_id,
        )

    def _resolve_email_pod_lifecycle_id(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> str | None:
        """Read-only shipment/thread resolution for duplicate email gate (no upserts)."""
        tid = self._clean(tenant_id)
        if not tid:
            return None

        existing_row_id = self._resolve_shipments_row_id(tenant_id=tid, payload=payload)
        if existing_row_id:
            return self._pod_lifecycle_id_for_shipment(
                tenant_id=tid,
                shipments_row_id=existing_row_id,
            )

        thread_id = self._clean(payload.get("thread_id"))
        if not thread_id:
            return None

        rows = self._communications.find_shipment_context_for_thread(
            tenant_id=tid,
            thread_id=thread_id,
        )
        picked = self._pick_thread_context(rows)
        if not picked:
            return None

        shipments_row_id, _, pod_lc_id = picked
        if pod_lc_id:
            return pod_lc_id
        return self._pod_lifecycle_id_for_shipment(
            tenant_id=tid,
            shipments_row_id=shipments_row_id,
        )

    def is_duplicate_email_pod_ingest(
        self,
        *,
        tenant_id: str,
        payload: dict[str, Any],
    ) -> bool:
        """True when lifecycle sub_status is at or past ``document_processed``."""
        lifecycle_id = self._resolve_email_pod_lifecycle_id(
            tenant_id=tenant_id,
            payload=payload,
        )
        if not lifecycle_id:
            return False

        row = self._lifecycle_service.read_lifecycle_row_by_id(lifecycle_id)
        sub = sub_status_type_from_db(row.get("sub_status") if row else None)
        return is_pod_processing_complete_sub_status(sub)
