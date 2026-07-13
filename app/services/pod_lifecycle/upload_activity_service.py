"""POD S3 upload activity logging after in-graph merge_and_upload_pod_attachments."""



from __future__ import annotations



from app.core.logger import get_logger

from app.domain.activity_log_descriptions import (

    format_pod_document_upload_failed_action,

    format_pod_document_uploaded_action,

    format_pod_uploaded_manually_info,

)

from app.domain.activity_log_write import ActivityLogSequence, ActivityLogStep

from app.domain.pod_lifecycle.activity_metadata import (

    upload_action_metadata,

    upload_failure_action_metadata,

)

from app.domain.pod_lifecycle.guards import (

    POD_UPLOAD_ACTIVITY_DONE_SUB_STATUSES,

    is_manual_pod_upload,

    pod_upload_success_from_state,

    should_skip_idempotent_pod_activity_log,

)

from app.domain.state import WorkflowState

from app.domain.status_parsing import status_type_from_db, sub_status_type_from_db

from app.models.activity_type import ActivityType, ActorType

from app.models.status import StatusSubType, StatusType

from app.services.activity_log_service import ActivityLogService

from app.services.workflow_lifecycle_service import WorkflowLifecycleService



logger = get_logger(__name__)





def _scope_ids(state: WorkflowState) -> tuple[str, str, str] | None:

    wl_id = str(state.data.get("workflow_lifecycle_id") or "").strip()

    tenant_id = (state.tenant_id or state.data.get("tenant_id") or "").strip()

    run_id = str(state.execution_id or "").strip()

    if not wl_id or not tenant_id or not run_id:

        return None

    return wl_id, tenant_id, run_id





def _communication_id(state: WorkflowState) -> str | None:

    raw = state.data.get("communication_id")

    if raw is None:

        return None

    cid = str(raw).strip()

    return cid or None





def _pod_document_persist(state: WorkflowState) -> dict | None:

    persist = state.data.get("documents_pod")

    return persist if isinstance(persist, dict) else None





def _build_upload_transition_step(

    *,

    current_status: StatusType | None,

    from_sub: StatusSubType,

) -> ActivityLogStep:

    to_status = StatusType.PROCESSING

    to_sub = StatusSubType.DOCUMENT_UPLOADED

    if current_status == to_status:

        return ActivityLogStep(

            activity_type=ActivityType.SUB_STATUS_CHANGE,

            to_status=to_status,

            to_sub_status=to_sub,

            from_sub_status=from_sub,

            metadata=None,

        )

    return ActivityLogStep(

        activity_type=ActivityType.STATUS_CHANGE,

        to_status=to_status,

        to_sub_status=to_sub,

        from_sub_status=from_sub,

        metadata=None,

    )





def _resolve_manual_actor(state: WorkflowState) -> tuple[ActorType, str | None]:

    user_id = str(state.data.get("uploaded_by_user_id") or "").strip()

    return ActorType.USER, user_id or None





class PodUploadActivityService:

    """Record POD S3 upload activity + lifecycle transitions."""



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

        Log POD S3 upload outcome after the pre-graph attachment pipeline.



        Manual success: INFO (Human) → processing/document_uploaded → S3 action.

        Email success: status transition → S3 action (comms on action when set).

        Failure: action + ``failed`` status.

        """

        scope = _scope_ids(state)

        if scope is None:

            logger.warning(

                "PodUploadActivityService skipped missing ids "

                "workflow_lifecycle_id=%r tenant_id=%r run_id=%r",

                bool(state.data.get("workflow_lifecycle_id")),

                bool(state.tenant_id or state.data.get("tenant_id")),

                bool(state.execution_id),

            )

            return



        wl_id, tenant_id, run_id = scope

        row = self._lifecycle_service.read_lifecycle_row_by_id(wl_id)

        if should_skip_idempotent_pod_activity_log(

            state.data,

            row,

            done_sub_statuses=POD_UPLOAD_ACTIVITY_DONE_SUB_STATUSES,

        ):

            logger.info(

                "PodUploadActivityService skipping already uploaded lifecycle_id=%s",

                wl_id,

            )

            return



        from_sub = sub_status_type_from_db(row.get("sub_status")) if row else StatusSubType.NONE

        if from_sub is None:

            from_sub = StatusSubType.NONE

        current_status = status_type_from_db(row.get("status")) if row else None

        is_manual = is_manual_pod_upload(state.data)



        if pod_upload_success_from_state(state.data):

            action_meta = upload_action_metadata(

                state.data,

                documents_pod=_pod_document_persist(state),

            )

            transition = _build_upload_transition_step(

                current_status=current_status,

                from_sub=from_sub,

            )

            s3_action = ActivityLogStep(

                activity_type=ActivityType.ACTION,

                description=format_pod_document_uploaded_action(),

                metadata=action_meta,

                communication_id=None if is_manual else _communication_id(state),

            )

            if is_manual:

                actor_type, actor_id = _resolve_manual_actor(state)

                self._activity_log_service.record_sequence(

                    ActivityLogSequence(

                        tenant_id=tenant_id,

                        workflow_lifecycle_id=wl_id,

                        workflow_run_id=run_id,

                        actor_type=actor_type,

                        actor_id=actor_id,

                        steps=(

                            ActivityLogStep(

                                activity_type=ActivityType.INFO,

                                description=format_pod_uploaded_manually_info(),

                                metadata=None,

                            ),

                        ),

                    )

                )

                self._activity_log_service.record_sequence(

                    ActivityLogSequence(

                        tenant_id=tenant_id,

                        workflow_lifecycle_id=wl_id,

                        workflow_run_id=run_id,

                        steps=(transition, s3_action),

                    )

                )

            else:

                self._activity_log_service.record_sequence(

                    ActivityLogSequence(

                        tenant_id=tenant_id,

                        workflow_lifecycle_id=wl_id,

                        workflow_run_id=run_id,

                        steps=(transition, s3_action),

                    )

                )

            return



        fail_meta = upload_failure_action_metadata(state.data)

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

                        description=format_pod_document_upload_failed_action(),

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


