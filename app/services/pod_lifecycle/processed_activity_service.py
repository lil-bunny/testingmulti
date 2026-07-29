"""POD processed-step activity logging (after LLM/ratecon)."""



from __future__ import annotations



from app.core.logger import get_logger

from app.domain.activity_log_descriptions import format_pod_document_processing_failed_action

from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep

from app.domain.pod_lifecycle.activity_metadata import processed_failure_action_metadata

from app.domain.pod_lifecycle.guards import (

    POD_PROCESSED_ACTIVITY_DONE_SUB_STATUSES,

    is_manual_pod_upload,

    pod_upload_success_from_state,

    should_skip_idempotent_pod_activity_log,

)


from app.domain.status_parsing import status_type_from_db

from app.models.activity_type import ActivityType

from app.models.status import StatusSubType, StatusType

from app.services.activity_log_service import ActivityLogService

from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.state import WorkflowState



logger = get_logger(__name__)





def _scope_ids(state: WorkflowState) -> tuple[str, str, str] | None:

    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()

    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()

    run_id = str(state.execution_id or "").strip()

    if not wl_id or not tenant_id or not run_id:

        return None

    return wl_id, tenant_id, run_id





def _analysis_success(state: WorkflowState) -> bool:

    persist = state.data.get("document_analysis_pod")

    return isinstance(persist, dict) and persist.get("stored") is True



def _build_reminder_transition_step(

    *,

    current_status: StatusType | None,

    new_sub: StatusSubType,

) -> ActivityLogStep:

    to_status = StatusType.PENDING_REVIEW

    if current_status == to_status:

        return ActivityLogStep(

            activity_type=ActivityType.SUB_STATUS_CHANGE,

            to_status=to_status,

            to_sub_status=new_sub,

            metadata=None,

        )

    return ActivityLogStep(

        activity_type=ActivityType.STATUS_CHANGE,

        to_status=to_status,

        to_sub_status=new_sub,

        metadata=None,

    )





class PodProcessedActivityService:

    """Record POD processed-step lifecycle transitions to phase-1 manual review."""



    def __init__(

        self,

        *,

        activity_log_service: ActivityLogService | None = None,

        lifecycle_service: WorkflowLifecycleService | None = None,

    ) -> None:

        self._activity_log_service = activity_log_service or ActivityLogService()

        self._lifecycle_service = lifecycle_service or WorkflowLifecycleService()



    def record_from_state(self, state: WorkflowState) -> None:

        """

        Finalize POD processing after LLM/ratecon.



        Email: ``pending_review`` + ``document_processed`` on success; ``failed`` on extraction miss.

        Both email and manual POD uploads transition to ``pending_review`` after
        successful analysis in phase 1. The score's PASS/FAIL is informational.

        """

        scope = _scope_ids(state)

        if scope is None:

            logger.warning(

                "PodProcessedActivityService skipped missing ids "

                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",

                bool(state.data.get("workflow_lifecycle_id")),

                bool(state.tenant_id or state.data.get("tenant_id")),

                bool(state.execution_id),

            )

            return



        if not pod_upload_success_from_state(state.data):

            return



        wl_id, tenant_id, run_id = scope

        row = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)

        if should_skip_idempotent_pod_activity_log(

            state.data,

            row,

            done_sub_statuses=POD_PROCESSED_ACTIVITY_DONE_SUB_STATUSES,

        ):

            logger.info(

                "PodProcessedActivityService skipping already processed lifecycle_id=%s",

                wl_id,

            )

            return



        if _analysis_success(state):

            current_status = status_type_from_db(row.get("status")) if row else None

            transition_step = _build_reminder_transition_step(

                current_status=current_status,

                new_sub=StatusSubType.DOCUMENT_PROCESSED,

            )

            self._activity_log_service.record_sequence(

                ActivityLogSequence(

                    tenant_id=tenant_id,

                    workflow_lifecycle_id=wl_id,

                    workflow_run_id=run_id,

                    steps=(transition_step,),

                )

            )

            return



        if is_manual_pod_upload(state.data):

            logger.info(

                "PodProcessedActivityService skipping manual (no extraction); TMS next lifecycle_id=%s",

                wl_id,

            )

            return



        fail_meta = processed_failure_action_metadata(state.data)

        from_status = status_type_from_db(row.get("status")) if row else StatusType.PROCESSING

        if from_status is None or from_status == StatusType.NONE:

            from_status = StatusType.PROCESSING

        self._activity_log_service.record_sequence(

            ActivityLogSequence(

                tenant_id=tenant_id,

                workflow_lifecycle_id=wl_id,

                workflow_run_id=run_id,

                steps=(

                    ActivityLogStep(

                        activity_type=ActivityType.ACTION,

                        description=format_pod_document_processing_failed_action(),

                        metadata=fail_meta,

                    ),

                    ActivityLogStep(

                        activity_type=ActivityType.STATUS_CHANGE,

                        to_status=StatusType.FAILED,

                        from_status=from_status,

                        metadata=None,

                    ),

                ),

            )

        )


