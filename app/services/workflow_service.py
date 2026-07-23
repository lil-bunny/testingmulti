from app.domain.tenant_settings.registry import tenant_settings_for_workflow_state
from app.domain.tenant_settings.workflow_shadow_mode import workflow_shadow_active
from app.services.execution_service import ExecutionService
from app.services.tenants_service import TenantsService
from app.services.ratecon_ingress_service import RateconIngressService
from app.services.pod_lifecycle.ingress_service import (
    POD_EMAIL_SKIP_INVALID_ATTACHMENT,
    ROUTE_COMPLETED_SKIP_CONVOY_LOAD,
    ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS,
    PodEmailIngressSkipped,
    PodLifecycleIngressService,
)
from app.services.pod_lifecycle.attachment_pipeline_service import (
    PodAttachmentPipelineService,
)
from app.services.driver_assignment.ingress_service import DriverAssignmentIngressService
from app.services.workflow_lifecycle_service import LifecycleResolution, WorkflowLifecycleService
from app.configs.workflow_template_contracts import WORKFLOW_TEMPLATE_CONTRACTS
from app.workflows.graph.builder import build_graph
from app.workflows.compiler.compiler import compile_graph
from app.workflows.graph.routers import (
    automatic_reply_ack_router,
    carrier_ack_router,
    event_type_router,
    routing_guide_router,
    tender_status_router,
    load_type_router,
    domestic_delivery_router,
    post_read_tender_router,
    manual_tms_upload_router,
    post_pod_processing_router,
    shipment_router,
    pod_exists_router,
    pod_missing_dispatch_router,
    ratecon_cache_router,
    read_workflow_lifecycle_router,
    driver_assignment_eligibility_router,
    driver_assignment_delayed_eligibility_router,
    driver_assignment_delayed_event_router,
    pod_reminder_eligibility_router,
    driver_details_router,
    tms_searchable_router,
    tms_driver_router,
    scheduling_intake_router,
    scheduling_prepare_router,
    appointment_scheduling_post_read_router,
    scheduling_weekend_shifted_router,
    customer_reply_router,
)
from app.models.workflow_run_event_type import WorkflowRunEventType
from typing import Optional
import uuid

from langsmith import traceable


ROUTER_REGISTRY = {
    "pod_exists": pod_exists_router,
    "pod_missing_dispatch": pod_missing_dispatch_router,
    "shipment_router": shipment_router,
    "event_type": event_type_router,
    "ratecon_cache_router": ratecon_cache_router,
    "read_workflow_lifecycle_router": read_workflow_lifecycle_router,
    "load_type_router": load_type_router,
    "tender_status_router": tender_status_router,
    "domestic_delivery_router": domestic_delivery_router,
    "post_read_tender_router": post_read_tender_router,
    "automatic_reply_ack_router": automatic_reply_ack_router,
    "carrier_ack_router": carrier_ack_router,
    "routing_guide_router": routing_guide_router,
    "manual_tms_upload_router": manual_tms_upload_router,
    "post_pod_processing_router": post_pod_processing_router,
    "driver_assignment_eligibility_router": driver_assignment_eligibility_router,
    "driver_assignment_delayed_eligibility_router": driver_assignment_delayed_eligibility_router,
    "driver_assignment_delayed_event_router": driver_assignment_delayed_event_router,
    "pod_reminder_eligibility_router": pod_reminder_eligibility_router,
    "driver_details_router": driver_details_router,
    "tms_searchable_router": tms_searchable_router,
    "tms_driver_router": tms_driver_router,
    "scheduling_intake_router": scheduling_intake_router,
    "scheduling_prepare_router": scheduling_prepare_router,
    "appointment_scheduling_post_read_router": appointment_scheduling_post_read_router,
    "scheduling_weekend_shifted_router": scheduling_weekend_shifted_router,
    "customer_reply_router": customer_reply_router,
}


class WorkflowService:

    def __init__(self, workflow_repo, tenant_repo):
        self.workflow_repo = workflow_repo
        self.tenant_repo = tenant_repo
        self.execution = ExecutionService()
        self.lifecycle_service = WorkflowLifecycleService()
        self.tenants_service = TenantsService()
        self._ratecon_ingress = RateconIngressService()
        self._pod_lifecycle_ingress = PodLifecycleIngressService()
        self._pod_attachment_pipeline = PodAttachmentPipelineService()
        self._driver_assignment_ingress = DriverAssignmentIngressService()

    @staticmethod
    def _skipped_driver_assignment_result(
        *,
        tenant_id: str,
        tenant_slug: str,
        payload: dict,
        reason: str,
    ) -> dict:
        execution_id = (
            str(payload.get("execution_id") or "").strip() or str(uuid.uuid4())
        )
        data = dict(payload)
        data["skipped_driver_assignment"] = True
        data["driver_assignment_skip_reason"] = reason
        return {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "execution_id": execution_id,
            "data": data,
        }

    @staticmethod
    def _skipped_route_completed_result(
        *,
        tenant_id: str,
        tenant_slug: str,
        payload: dict,
        lifecycle_id: str | None,
        reason: str | None = None,
    ) -> dict:
        execution_id = str(payload.get("execution_id") or "").strip() or str(uuid.uuid4())
        data = dict(payload)
        if reason == ROUTE_COMPLETED_SKIP_CONVOY_LOAD:
            data["skipped_convoy_load"] = True
            data["route_completed_skip_reason"] = reason
        elif reason == ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS:
            data["skipped_pod_already_exists"] = True
            data["route_completed_skip_reason"] = reason
        else:
            data["skipped_duplicate_route_completed"] = True
        if lifecycle_id:
            data["workflow_lifecycle_id"] = lifecycle_id
        return {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "execution_id": execution_id,
            "data": data,
        }

    @staticmethod
    def _skipped_pod_email_ingress_result(
        *,
        tenant_id: str,
        tenant_slug: str,
        payload: dict,
        reason: str,
        shipments_row_id: str | None = None,
    ) -> dict:
        execution_id = str(payload.get("execution_id") or "").strip() or str(uuid.uuid4())
        data = dict(payload)
        data["skipped_pod_email_ingress"] = True
        data["pod_email_ingress_skip_reason"] = reason
        if shipments_row_id:
            data["shipments_row_id"] = shipments_row_id
        return {
            "tenant_id": tenant_id,
            "tenant_slug": tenant_slug,
            "execution_id": execution_id,
            "data": data,
        }

    def _stamp_pod_lifecycle_before_attachment_pipeline(
        self,
        *,
        tenant_id: str,
        payload: dict,
    ) -> None:
        """Resolve lifecycle before pre-graph classify so LangSmith thread_id matches the graph."""
        lifecycle = self.lifecycle_service.resolve_or_create_lifecycle(
            tenant_id=tenant_id,
            workflow_name="pod_lifecycle",
            payload=payload,
        )
        payload["workflow_lifecycle_id"] = lifecycle.workflow_lifecycle_id
        payload["workflow_name"] = "pod_lifecycle"

    async def run(
        self,
        tenant_slug: str,
        workflow_name: str,
        payload: Optional[dict] = None,
    ):
        payload = payload or {}
        tenant_row = self.tenants_service.get_by_slug(tenant_slug)
        if tenant_row is None:
            raise Exception(f"Unknown tenant slug: {tenant_slug!r}")
        tenant_id = tenant_row["id"]

        payload["tenant_id"] = tenant_id
        payload["tenant_slug"] = tenant_slug
        payload["tenant_settings"] = tenant_settings_for_workflow_state(
            tenant_slug,
            tenant_row.get("settings") or {},
            workflow_name=workflow_name,
        )
        if workflow_name == "pod_lifecycle":
            payload = self._pod_lifecycle_ingress.enrich_payload_load_id(
                tenant_id=tenant_id,
                payload=payload,
            )
        if workflow_shadow_active(
            payload["tenant_settings"],
            payload,
            workflow_name=workflow_name,
        ):
            payload["workflow_shadow_mode"] = True

        if workflow_name == "ratecon":
            payload = await self._ratecon_ingress.prepare_payload(
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                payload=payload,
            )

        if (
            workflow_name == "driver_assignment"
            and payload.get("event_type")
            == WorkflowRunEventType.RATECON_COMPLETED.value
        ):
            prepared = await self._driver_assignment_ingress.prepare_ratecon_completed_payload(
                tenant_id=tenant_id,
                tenant_slug=tenant_slug,
                payload=payload,
            )
            if prepared.skipped:
                return self._skipped_driver_assignment_result(
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                    payload=payload,
                    reason=prepared.skip_reason or "unknown",
                )
            payload = prepared.payload or payload

        if (
            workflow_name == "pod_lifecycle"
            and payload.get("event_type") == "email_received"
        ):
            if not str(payload.get("execution_id") or "").strip():
                payload["execution_id"] = str(uuid.uuid4())
            try:
                payload = await self._pod_lifecycle_ingress.prepare_email_received_payload(
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                    payload=payload,
                )
            except PodEmailIngressSkipped as skip:
                return self._skipped_pod_email_ingress_result(
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                    payload=payload,
                    reason=skip.reason,
                    shipments_row_id=skip.shipments_row_id,
                )

            # Lifecycle before classify: achat_vision_json must use workflow_lifecycle_id
            # as LangSmith thread_id (not execution_id), matching workflow:pod_lifecycle.
            self._stamp_pod_lifecycle_before_attachment_pipeline(
                tenant_id=tenant_id,
                payload=payload,
            )

            pipeline = await self._pod_attachment_pipeline.run_for_email_payload(
                payload=payload,
            )
            if not pipeline.success:
                return self._skipped_pod_email_ingress_result(
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                    payload=payload,
                    reason=pipeline.skip_reason or POD_EMAIL_SKIP_INVALID_ATTACHMENT,
                    shipments_row_id=payload.get("shipments_row_id"),
                )
            if pipeline.state_patch:
                payload.update(pipeline.state_patch)

        if (
            workflow_name == "pod_lifecycle"
            and payload.get("event_type") == "manual_pod_upload"
            and payload.get("manual_pod_upload_source") != "stored"
            and not (
                isinstance(payload.get("documents_pod"), dict)
                and payload["documents_pod"].get("stored")
            )
        ):
            if not str(payload.get("execution_id") or "").strip():
                payload["execution_id"] = str(uuid.uuid4())
            self._stamp_pod_lifecycle_before_attachment_pipeline(
                tenant_id=tenant_id,
                payload=payload,
            )
            pipeline = await self._pod_attachment_pipeline.run_for_object_keys(
                pod_object_keys=list(payload.get("pod_object_keys") or []),
                shipment_id=str(payload.get("shipment_id") or "").strip() or None,
                shipments_row_id=str(payload.get("shipments_row_id") or "").strip()
                or None,
                stage_token=(
                    str(payload.get("workflow_lifecycle_id") or "").strip()
                    or str(payload.get("execution_id") or "").strip()
                    or None
                ),
                trace_payload=payload,
            )
            if not pipeline.success:
                raise Exception(
                    "pod_lifecycle manual_pod_upload: attachment pipeline failed: "
                    f"{pipeline.skip_reason or 'unknown'}"
                )
            if pipeline.state_patch:
                payload.update(pipeline.state_patch)

        if (
            workflow_name == "pod_lifecycle"
            and payload.get("event_type") == "route_completed"
        ):
            duplicate = self._pod_lifecycle_ingress.check_route_completed_duplicate(
                tenant_id=tenant_id,
                payload=payload,
            )
            if duplicate.is_duplicate:
                return self._skipped_route_completed_result(
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                    payload=payload,
                    lifecycle_id=duplicate.lifecycle_id,
                )

            convoy_gate = await self._pod_lifecycle_ingress.check_route_completed_convoy_gate(
                tenant_slug=tenant_slug,
                payload=payload,
            )
            if convoy_gate.skip:
                return self._skipped_route_completed_result(
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                    payload=payload,
                    lifecycle_id=None,
                    reason=convoy_gate.reason or ROUTE_COMPLETED_SKIP_CONVOY_LOAD,
                )

            pod_gate = await self._pod_lifecycle_ingress.check_route_completed_pod_gate(
                tenant_slug=tenant_slug,
                payload=payload,
            )
            if pod_gate.skip:
                return self._skipped_route_completed_result(
                    tenant_id=tenant_id,
                    tenant_slug=tenant_slug,
                    payload=payload,
                    lifecycle_id=None,
                    reason=pod_gate.reason or ROUTE_COMPLETED_SKIP_POD_ALREADY_EXISTS,
                )

        deferred_scheduling_lifecycle = (
            workflow_name == "appointment_scheduling"
            and payload.get("event_type")
            == WorkflowRunEventType.TURVO_PICKUP_CHANGED.value
            and not str(payload.get("workflow_lifecycle_id") or "").strip()
        )
        if deferred_scheduling_lifecycle:
            payload["execution_id"] = (
                str(payload.get("execution_id") or "").strip() or str(uuid.uuid4())
            )

        lifecycle = (
            self.lifecycle_service.resolve_driver_assignment_cycle(
                tenant_id=tenant_id,
                payload=payload,
            )
            if (
                workflow_name == "driver_assignment"
                and payload.get("event_type")
                == WorkflowRunEventType.RATECON_COMPLETED.value
            )
            else (
                LifecycleResolution(
                    workflow_lifecycle_id=str(payload["workflow_lifecycle_id"]).strip(),
                    existed=True,
                )
                if (
                    workflow_name == "appointment_scheduling"
                    and payload.get("event_type")
                    in (
                        WorkflowRunEventType.APPOINTMENT_DRAFT_SEND.value,
                        WorkflowRunEventType.APPOINTMENT_CUSTOMER_REPLY_RECEIVED.value,
                    )
                    and str(payload.get("workflow_lifecycle_id") or "").strip()
                )
                else (
                    LifecycleResolution(
                        workflow_lifecycle_id=str(payload["execution_id"]).strip(),
                        existed=False,
                    )
                    if deferred_scheduling_lifecycle
                    else self.lifecycle_service.resolve_or_create_lifecycle(
                        tenant_id=tenant_id,
                        workflow_name=workflow_name,
                        payload=payload,
                    )
                )
            )
        )
        workflow_lifecycle_id = lifecycle.workflow_lifecycle_id
        payload["workflow_lifecycle_id"] = workflow_lifecycle_id
        payload["workflow_name"] = workflow_name

        if not deferred_scheduling_lifecycle:
            shipments_row_id = self.lifecycle_service.ensure_lifecycle_shipment_linked(
                lifecycle_id=workflow_lifecycle_id,
                tenant_id=tenant_id,
                payload=payload,
            )
            if shipments_row_id:
                payload["shipments_row_id"] = shipments_row_id

        event_type = payload.get("event_type")
        traced = traceable(
            run_type="chain",
            name=f"workflow:{workflow_name}",
        )(self._run_impl)
        return await traced(
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            workflow_name=workflow_name,
            payload=payload,
            langsmith_extra={
                "metadata": {
                    "thread_id": workflow_lifecycle_id,
                    "workflow_lifecycle_id": workflow_lifecycle_id,
                    "tenant_id": tenant_id,
                    "tenant_slug": tenant_slug,
                    "event_type": event_type,
                    "shipment_id": payload.get("shipment_id"),
                    "tender_id": payload.get("tender_id"),
                    "order_number": payload.get("order_number"),
                    "email_thread_id": payload.get("email_thread_id") or payload.get("thread_id"),
                }
            },
        )

    async def _run_impl(
        self,
        tenant_id: str,
        tenant_slug: str,
        workflow_name: str,
        payload: Optional[dict] = None,
    ):
        contract = WORKFLOW_TEMPLATE_CONTRACTS.get(workflow_name)
        if not contract:
            raise Exception(f"Unknown workflow contract: {workflow_name}")

        payload = payload or {}
        workflow_lifecycle_id = str(payload.get("workflow_lifecycle_id") or "").strip()
        if not workflow_lifecycle_id:
            if (
                workflow_name == "appointment_scheduling"
                and payload.get("event_type")
                == WorkflowRunEventType.TURVO_PICKUP_CHANGED.value
            ):
                workflow_lifecycle_id = str(payload.get("execution_id") or "").strip()
            if not workflow_lifecycle_id:
                raise Exception("Missing workflow_lifecycle_id")
        missing_keys = [k for k in contract.required_state_keys if k not in payload]
        if missing_keys:
            raise Exception(
                f"Missing required payload keys for '{workflow_name}': {missing_keys}"
            )

        base_graph = self.workflow_repo.get(workflow_name)
        tenant_config = self.tenant_repo.get_config(tenant_slug).get(workflow_name, {})

        compiled = compile_graph(base_graph, tenant_config)

        graph = build_graph(compiled, ROUTER_REGISTRY)

        execution_id = payload.get("execution_id", None)
        # execution_id = (
        #     pre_assigned.strip()
        #     if isinstance(pre_assigned, str) and pre_assigned.strip()
        #     else None
        # )

        return await self.execution.execute(
            graph=graph,
            tenant_id=tenant_id,
            tenant_slug=tenant_slug,
            workflow_lifecycle_id=workflow_lifecycle_id,
            payload=payload,
            execution_id=execution_id,
        )