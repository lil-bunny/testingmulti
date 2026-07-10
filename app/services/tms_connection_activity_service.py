"""Audit EXCEPTION rows when Turvo transient HTTP retries are exhausted."""

from __future__ import annotations

from app.core.logger import get_logger
from app.domain.activity_log_descriptions import format_tms_connection_timed_out_description
from app.domain.activity_log_write import ActivityLogWrite
from app.models.activity_type import ActorType
from app.services.activity_log_service import ActivityLogService

logger = get_logger(__name__)


class TmsConnectionActivityService:
    def __init__(self, *, activity_log_service: ActivityLogService | None = None) -> None:
        self._activity = activity_log_service or ActivityLogService()

    def record_timeout(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        workflow_run_id: str | None = None,
        communication_id: str | None = None,
    ) -> str | None:
        wl_id = str(workflow_lifecycle_id or "").strip()
        tenant = str(tenant_id or "").strip()
        if not wl_id or not tenant:
            logger.warning(
                "tms_connection_activity skipped missing scope wl_id=%r tenant_id=%r",
                bool(wl_id),
                bool(tenant),
            )
            return None
        comm_id = str(communication_id or "").strip() or None
        run_id = str(workflow_run_id or "").strip() or None
        try:
            return self._activity.record_exception(
                ActivityLogWrite(
                    tenant_id=tenant,
                    workflow_lifecycle_id=wl_id,
                    workflow_run_id=run_id,
                    description=format_tms_connection_timed_out_description(),
                    metadata=None,
                    communication_id=comm_id,
                    actor_type=ActorType.SYSTEM,
                )
            )
        except Exception:
            logger.exception(
                "tms_connection_activity record_timeout failed wl_id=%s tenant_id=%s",
                wl_id,
                tenant,
            )
            return None
