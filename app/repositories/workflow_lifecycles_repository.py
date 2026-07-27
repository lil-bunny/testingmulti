"""Reads/writes for ``workflow_lifecycles``."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from sqlalchemy import text

from app.core.db import jsonb_param, parse_json
from app.models.status import StatusSubType, StatusType

if TYPE_CHECKING:
    from app.models.pause_type import PauseType
    from sqlalchemy.orm import Session


@dataclass(frozen=True)
class LifecycleUpdate:
    """One atomic write into ``workflow_lifecycles`` row.

    ``pause_type`` set means write that value; ``clear_pause=True`` means write NULL.
    If both are unset, ``pause_type`` is not touched. ``clear_pause`` is ignored when
    ``pause_type`` is provided.
    """

    status: StatusType | None = None
    sub_status: StatusSubType | None = None
    pause_type: PauseType | None = None
    clear_pause: bool = False

    def has_changes(self) -> bool:
        return (
            self.status is not None
            or self.sub_status is not None
            or self.pause_type is not None
            or self.clear_pause
        )

_WHERE_LIFECYCLE_ID = """
    WHERE id = CAST(:lifecycle_id AS uuid)
"""

_WHERE_TENANT_WORKFLOW = """
    WHERE tenant_id = CAST(:tenant_id AS uuid)
      AND workflow_name = :workflow_name
"""

_LOOKUP_ORDER_LIMIT = """
    ORDER BY updated_at DESC
    LIMIT 1
"""


class WorkflowLifecyclesRepository:
    TABLE_NAME = "workflow_lifecycles"

    def __init__(self, session: Session) -> None:
        self._session = session

    def _fetch_lifecycle_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        extra_predicate: str,
        extra_params: dict[str, Any],
    ) -> str | None:
        sql = f"""
            SELECT id::text
            FROM {self.TABLE_NAME}
            {_WHERE_TENANT_WORKFLOW}
              {extra_predicate}
            {_LOOKUP_ORDER_LIMIT}
        """
        params = {
            "tenant_id": tenant_id,
            "workflow_name": workflow_name,
            **extra_params,
        }
        row = self._session.execute(text(sql), params).first()
        if row and row[0]:
            return str(row[0])
        return None

    def get_for_update(
        self,
        *,
        lifecycle_id: str,
    ) -> dict[str, Any] | None:
        row = self._session.execute(
            text(
                f"""
                SELECT status::text, sub_status::text, tenant_id::text, workflow_name
                FROM {self.TABLE_NAME}
                {_WHERE_LIFECYCLE_ID}
                FOR UPDATE
                """
            ),
            {"lifecycle_id": lifecycle_id},
        ).first()
        if not row:
            return None
        return {
            "status": row[0],
            "sub_status": row[1],
            "tenant_id": row[2],
            "workflow_name": row[3],
        }

    def update_status(
        self,
        *,
        lifecycle_id: str,
        status: StatusType | None = None,
        sub_status: StatusSubType | None = None,
    ) -> bool:
        return self.update_lifecycle(
            lifecycle_id=lifecycle_id,
            update=LifecycleUpdate(status=status, sub_status=sub_status),
        )

    def update_lifecycle(
        self,
        *,
        lifecycle_id: str,
        update: LifecycleUpdate,
    ) -> bool:
        """Single-statement update of status / sub_status / pause_type."""
        if not update.has_changes():
            return False

        updates: list[str] = []
        params: dict[str, Any] = {"lifecycle_id": lifecycle_id}

        if update.status is not None:
            updates.append("status = CAST(:status AS lifecycle_status)")
            params["status"] = update.status.value

        if update.sub_status is not None:
            updates.append("sub_status = CAST(:sub_status AS lifecycle_sub_status)")
            params["sub_status"] = update.sub_status.value

        if update.pause_type is not None:
            updates.append("pause_type = CAST(:pause_type AS lifecycle_pause_type)")
            params["pause_type"] = update.pause_type.value
        elif update.clear_pause:
            updates.append("pause_type = NULL")

        updates.append("updated_at = NOW()")
        sql = f"""
            UPDATE {self.TABLE_NAME}
            SET {", ".join(updates)}
            {_WHERE_LIFECYCLE_ID}
        """
        result = self._session.execute(text(sql), params)
        return result.rowcount > 0

    def update_shipment_id(
        self,
        *,
        lifecycle_id: str,
        shipment_id: str,
    ) -> bool:
        """Set ``shipment_id`` FK only when currently NULL (idempotent)."""
        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET shipment_id = CAST(:shipment_id AS uuid), updated_at = NOW()
                WHERE id = CAST(:lifecycle_id AS uuid)
                  AND shipment_id IS NULL
                """
            ),
            {"shipment_id": shipment_id, "lifecycle_id": lifecycle_id},
        )
        return result.rowcount > 0

    def _find_existing_lifecycle_id_shipment_first(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> str | None:
        """ratecon / pod_lifecycle: ``shipment_id`` FK (UUID) only."""
        if not shipment_id:
            return None
        extra_predicate = "AND shipment_id = CAST(:shipment_id AS uuid)"
        extra_params: dict[str, Any] = {"shipment_id": shipment_id}
        if workflow_name == "ratecon":
            extra_predicate += (
                " AND sub_status != CAST(:cancelled AS lifecycle_sub_status)"
            )
            extra_params["cancelled"] = StatusSubType.CANCELLED.value
        return self._fetch_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            extra_predicate=extra_predicate,
            extra_params=extra_params,
        )

    def find_latest_non_cancelled_lifecycle_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        shipment_id: str,
    ) -> str | None:
        if not shipment_id:
            return None
        return self._fetch_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            extra_predicate=(
                "AND shipment_id = CAST(:shipment_id AS uuid)"
                " AND sub_status != CAST(:cancelled AS lifecycle_sub_status)"
            ),
            extra_params={
                "shipment_id": shipment_id,
                "cancelled": StatusSubType.CANCELLED.value,
            },
        )

    def find_existing_lifecycle_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> str | None:
        """
        Resolve lifecycle PK by correlation keys.

        ratecon / pod_lifecycle: ``shipment_id`` FK only.
        Other workflows (e.g. load_tendering): ``tender_id`` → ``shipment_id``.
        """
        if workflow_name in ("ratecon", "pod_lifecycle"):
            return self._find_existing_lifecycle_id_shipment_first(
                tenant_id=tenant_id,
                workflow_name=workflow_name,
                thread_id=thread_id,
                shipment_id=shipment_id,
            )

        if tender_id:
            found = self._fetch_lifecycle_id(
                tenant_id=tenant_id,
                workflow_name=workflow_name,
                extra_predicate="AND tender_id = CAST(:tender_id AS uuid)",
                extra_params={"tender_id": tender_id},
            )
            if found:
                return found

        if shipment_id:
            found = self._fetch_lifecycle_id(
                tenant_id=tenant_id,
                workflow_name=workflow_name,
                extra_predicate="AND shipment_id = CAST(:shipment_id AS uuid)",
                extra_params={"shipment_id": shipment_id},
            )
            if found:
                return found
        return None

    def insert_lifecycle(
        self,
        *,
        lifecycle_id: str,
        tenant_id: str,
        workflow_name: str,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> None:
        self._session.execute(
            text(
                f"""
                INSERT INTO {self.TABLE_NAME} (
                    id,
                    tenant_id,
                    workflow_name,
                    tender_id,
                    shipment_id
                ) VALUES (
                    CAST(:lifecycle_id AS uuid),
                    CAST(:tenant_id AS uuid),
                    :workflow_name,
                    CAST(:tender_id AS uuid),
                    CAST(:shipment_id AS uuid)
                )
                """
            ),
            {
                "lifecycle_id": lifecycle_id,
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "tender_id": tender_id,
                "shipment_id": shipment_id,
            },
        )

    def _row_dict_from_select(self, row: Any) -> dict[str, Any]:
        metadata = parse_json(row[6]) if len(row) > 6 else {}
        return {
            "id": row[0],
            "tenant_id": row[1],
            "workflow_name": row[2],
            "status": row[3],
            "sub_status": row[4],
            "tender_id": row[5] or "",
            "metadata": metadata,
        }

    def set_routing_guide_attempt(self, *, lifecycle_id: str, attempt: int) -> bool:
        """Persist waterfall depth on ``workflow_lifecycles.metadata``."""
        lid = str(lifecycle_id or "").strip()
        try:
            value = int(attempt)
        except (TypeError, ValueError):
            return False
        if not lid or value < 1:
            return False

        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET metadata = COALESCE(metadata, '{{}}'::jsonb) || jsonb_build_object(
                        'routing_guide_attempt', to_jsonb(CAST(:attempt AS integer))
                    ),
                    updated_at = NOW()
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {"attempt": value, "lifecycle_id": lid},
        )
        return result.rowcount > 0

    def read_row_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Return lifecycle row fields for a PK."""
        row = self._session.execute(
            text(
                f"""
                SELECT id::text, tenant_id::text, workflow_name, status::text, sub_status::text,
                       tender_id::text, metadata
                FROM {self.TABLE_NAME}
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {"lifecycle_id": lifecycle_id},
        ).first()
        if not row:
            return None
        return self._row_dict_from_select(row)

    def read_row_by_tender_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: str,
    ) -> dict[str, Any] | None:
        """Return the latest lifecycle row for tenant/workflow/tender correlation."""
        row = self._session.execute(
            text(
                f"""
                SELECT id::text, tenant_id::text, workflow_name, status::text, sub_status::text,
                       tender_id::text, metadata
                FROM {self.TABLE_NAME}
                {_WHERE_TENANT_WORKFLOW}
                  AND tender_id = CAST(:tender_id AS uuid)
                {_LOOKUP_ORDER_LIMIT}
                """
            ),
            {
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "tender_id": tender_id,
            },
        ).first()
        if not row:
            return None
        return self._row_dict_from_select(row)

    def read_correlation_by_id(self, lifecycle_id: str) -> dict[str, Any] | None:
        """Shipment/thread/tender fields for ``read_lifecycle`` responses."""
        row = self._session.execute(
            text(
                f"""
                SELECT shipment_id::text, workflow_name, tender_id::text
                FROM {self.TABLE_NAME}
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {"lifecycle_id": lifecycle_id},
        ).first()
        if not row:
            return None
        return {
            "shipment_id": row[0] or "",
            "workflow_name": row[1] or "",
            "tender_id": row[2] or "",
        }

    def find_existing_lifecycle_id_tx(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> str | None:
        return self.find_existing_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            tender_id=tender_id,
            thread_id=thread_id,
            shipment_id=shipment_id,
        )

    def resolve_or_create(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        tender_id: str | None = None,
        thread_id: str | None = None,
        shipment_id: str | None = None,
    ) -> tuple[str, bool]:
        """Return ``(lifecycle_id, existed)`` without committing."""
        existing_id = self.find_existing_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            tender_id=tender_id,
            thread_id=thread_id,
            shipment_id=shipment_id,
        )
        if existing_id:
            return existing_id, True

        new_id = str(uuid.uuid4())
        self.insert_lifecycle(
            lifecycle_id=new_id,
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            tender_id=tender_id,
            thread_id=thread_id,
            shipment_id=shipment_id,
        )
        return new_id, False

    def update_shipment_id_tx(
        self,
        *,
        lifecycle_id: str,
        shipment_id: str,
    ) -> bool:
        return self.update_shipment_id(
            lifecycle_id=lifecycle_id,
            shipment_id=shipment_id,
        )

    def update_lifecycle_status_tx(
        self,
        *,
        lifecycle_id: str,
        status: StatusType | None = None,
        sub_status: StatusSubType | None = None,
    ) -> bool:
        return self.update_status(
            lifecycle_id=lifecycle_id,
            status=status,
            sub_status=sub_status,
        )

    def update_lifecycle_sub_status_tx(
        self,
        *,
        lifecycle_id: str,
        new_sub_status: StatusSubType,
    ) -> bool:
        result = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET
                    sub_status = CAST(:sub_status AS lifecycle_sub_status),
                    updated_at = NOW()
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {
                "sub_status": new_sub_status.value,
                "lifecycle_id": lifecycle_id,
            },
        )
        return result.rowcount > 0

    def find_in_progress_lifecycle_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        shipment_id: str,
        in_progress_statuses: tuple[str, ...],
        excluded_sub_statuses: tuple[str, ...],
    ) -> str | None:
        if not shipment_id or not in_progress_statuses:
            return None
        status_slots = ", ".join(
            f"CAST(:status_{i} AS lifecycle_status)"
            for i in range(len(in_progress_statuses))
        )
        extra_params: dict[str, Any] = {
            "shipment_id": shipment_id,
        }
        for i, val in enumerate(in_progress_statuses):
            extra_params[f"status_{i}"] = val

        sub_filter = ""
        if excluded_sub_statuses:
            sub_slots = ", ".join(
                f"CAST(:excluded_sub_{i} AS lifecycle_sub_status)"
                for i in range(len(excluded_sub_statuses))
            )
            sub_filter = f" AND sub_status NOT IN ({sub_slots})"
            for i, val in enumerate(excluded_sub_statuses):
                extra_params[f"excluded_sub_{i}"] = val

        return self._fetch_lifecycle_id(
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            extra_predicate=(
                "AND shipment_id = CAST(:shipment_id AS uuid)"
                f" AND status IN ({status_slots})"
                f"{sub_filter}"
            ),
            extra_params=extra_params,
        )

    def has_success_terminal_driver_assignment_lifecycle(
        self,
        *,
        tenant_id: str,
        shipment_id: str,
    ) -> bool:
        if not shipment_id:
            return False
        row = self._session.execute(
            text(
                f"""
                SELECT 1
                FROM {self.TABLE_NAME}
                {_WHERE_TENANT_WORKFLOW}
                  AND shipment_id = CAST(:shipment_id AS uuid)
                  AND sub_status IN (
                      CAST(:uploaded AS lifecycle_sub_status)
                  )
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "workflow_name": "driver_assignment",
                "shipment_id": shipment_id,
                "uploaded": StatusSubType.UPLOADED_TO_TMS.value,
            },
        ).first()
        return row is not None

    def patch_metadata(
        self,
        *,
        lifecycle_id: str,
        metadata_patch: dict[str, Any],
    ) -> bool:
        """Merge ``metadata_patch`` into ``workflow_lifecycles.metadata``."""
        rowcount = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET metadata = COALESCE(metadata, '{{}}'::jsonb) || CAST(:metadata_patch AS jsonb),
                    updated_at = NOW()
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {
                "lifecycle_id": lifecycle_id,
                "metadata_patch": jsonb_param(metadata_patch or {}),
            },
        ).rowcount
        return rowcount > 0

    def claim_appointment_draft_send_queued(
        self,
        *,
        lifecycle_id: str,
        expected_tenant_id: str,
    ) -> str:
        """Atomically claim portal draft send via ``metadata.draft_send_queued``.

        Returns one of: ``claimed``, ``not_found``, ``conflict``, ``invalid_status``,
        ``scheduling_draft_not_ready``.
        """
        from app.domain.appointment_scheduling.constants import (
            DRAFT_SEND_QUEUED,
            EMAIL_DRAFT,
        )
        from app.domain.error_catalog import BusinessError

        row = self._session.execute(
            text(
                f"""
                SELECT status::text, sub_status::text, tenant_id::text, metadata
                FROM {self.TABLE_NAME}
                {_WHERE_LIFECYCLE_ID}
                FOR UPDATE
                """
            ),
            {"lifecycle_id": lifecycle_id},
        ).first()
        if not row:
            return "not_found"

        row_tenant = str(row[2] or "").strip()
        if row_tenant != str(expected_tenant_id or "").strip():
            return "not_found"

        status = str(row[0] or "").strip()
        sub_status = str(row[1] or "").strip()
        if status != StatusType.PENDING_REVIEW.value:
            return "invalid_status"
        if sub_status != StatusSubType.APPOINTMENT_DRAFT_CREATED.value:
            return "conflict"

        meta = parse_json(row[3]) if row[3] is not None else {}
        if not isinstance(meta, dict):
            meta = {}
        if meta.get(DRAFT_SEND_QUEUED) is True:
            return "conflict"

        draft = meta.get(EMAIL_DRAFT)
        if not isinstance(draft, dict) or not (
            str(draft.get("to") or "").strip()
            and str(draft.get("subject") or "").strip()
            and str(draft.get("full_html") or "").strip()
        ):
            return BusinessError.SCHEDULING_DRAFT_NOT_READY.value

        updated = self._session.execute(
            text(
                f"""
                UPDATE {self.TABLE_NAME}
                SET metadata = COALESCE(metadata, '{{}}'::jsonb) || CAST(:metadata_patch AS jsonb),
                    updated_at = NOW()
                {_WHERE_LIFECYCLE_ID}
                  AND status = CAST(:status AS lifecycle_status)
                  AND sub_status = CAST(:sub_status AS lifecycle_sub_status)
                  AND COALESCE((metadata->>'draft_send_queued')::boolean, false) IS NOT TRUE
                """
            ),
            {
                "lifecycle_id": lifecycle_id,
                "metadata_patch": jsonb_param({DRAFT_SEND_QUEUED: True}),
                "status": StatusType.PENDING_REVIEW.value,
                "sub_status": StatusSubType.APPOINTMENT_DRAFT_CREATED.value,
            },
        ).rowcount
        return "claimed" if updated > 0 else "conflict"

    def insert_driver_assignment_lifecycle(
        self,
        *,
        tenant_id: str,
        shipment_id: str,
    ) -> str:
        new_id = str(uuid.uuid4())
        self.insert_lifecycle(
            lifecycle_id=new_id,
            tenant_id=tenant_id,
            workflow_name="driver_assignment",
            shipment_id=shipment_id,
        )
        return new_id

    def find_blocking_appointment_scheduling_lifecycle_id(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        shipment_number: str,
    ) -> str | None:
        """Return lifecycle id when a non-restartable appointment_scheduling row exists."""
        number = str(shipment_number or "").strip()
        if not number:
            return None
        row = self._session.execute(
            text(
                """
                SELECT wl.id::text
                FROM workflow_lifecycles wl
                INNER JOIN shipments s ON s.id = wl.shipment_id
                WHERE wl.tenant_id = CAST(:tenant_id AS uuid)
                  AND wl.workflow_name = :workflow_name
                  AND s.shipment_number = :shipment_number
                  AND NOT (
                      wl.status = CAST(:failed_status AS lifecycle_status)
                      OR wl.sub_status = CAST(:resolved_manually AS lifecycle_sub_status)
                      OR (
                          wl.status = CAST(:pending_review_status AS lifecycle_status)
                          AND NULLIF(wl.metadata->>'appointment_failure_reason', '') IS NOT NULL
                      )
                  )
                ORDER BY wl.updated_at DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "shipment_number": number,
                "failed_status": StatusType.FAILED.value,
                "resolved_manually": StatusSubType.RESOLVED_MANUALLY.value,
                "pending_review_status": StatusType.PENDING_REVIEW.value,
            },
        ).first()
        if row and row[0]:
            return str(row[0])
        return None

    def insert_appointment_scheduling_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_name: str,
        shipment_id: str,
        lifecycle_id: str | None = None,
    ) -> str:
        """Insert lifecycle, or attach ``shipment_id`` to an existing deferred stub."""
        new_id = str(lifecycle_id or "").strip() or str(uuid.uuid4())
        existing = self._session.execute(
            text(
                f"""
                SELECT 1
                FROM {self.TABLE_NAME}
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {"lifecycle_id": new_id},
        ).first()
        if existing:
            self.update_shipment_id(lifecycle_id=new_id, shipment_id=shipment_id)
            return new_id
        self.insert_lifecycle(
            lifecycle_id=new_id,
            tenant_id=tenant_id,
            workflow_name=workflow_name,
            shipment_id=shipment_id,
        )
        return new_id

    def ensure_lifecycle_stub(
        self,
        *,
        lifecycle_id: str,
        tenant_id: str,
        workflow_name: str,
    ) -> bool:
        """Insert a shipment-less lifecycle row if missing (deferred Turvo ingress).

        Returns True when a new row was inserted, False if it already existed.
        """
        lid = str(lifecycle_id or "").strip()
        tid = str(tenant_id or "").strip()
        wn = str(workflow_name or "").strip()
        if not lid or not tid or not wn:
            return False
        existing = self._session.execute(
            text(
                f"""
                SELECT 1
                FROM {self.TABLE_NAME}
                {_WHERE_LIFECYCLE_ID}
                """
            ),
            {"lifecycle_id": lid},
        ).first()
        if existing:
            return False
        self.insert_lifecycle(
            lifecycle_id=lid,
            tenant_id=tid,
            workflow_name=wn,
            shipment_id=None,
        )
        return True

    def find_awaiting_customer_reply_lifecycle_id(
        self,
        *,
        tenant_id: str,
        shipment_id: str,
        workflow_name: str = "appointment_scheduling",
    ) -> str | None:
        """Latest lifecycle awaiting customer reply for a shipment row."""
        sid = str(shipment_id or "").strip()
        if not sid:
            return None
        row = self._session.execute(
            text(
                """
                SELECT wl.id::text
                FROM workflow_lifecycles wl
                WHERE wl.tenant_id = CAST(:tenant_id AS uuid)
                  AND wl.workflow_name = :workflow_name
                  AND wl.shipment_id = CAST(:shipment_id AS uuid)
                  AND wl.sub_status = CAST(:awaiting_reply AS lifecycle_sub_status)
                ORDER BY wl.updated_at DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "shipment_id": sid,
                "awaiting_reply": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
            },
        ).first()
        if row and row[0]:
            return str(row[0])
        return None

    def find_awaiting_customer_reply_by_appt_subject_token(
        self,
        *,
        tenant_id: str,
        subject_token: str,
        workflow_name: str = "appointment_scheduling",
    ) -> str | None:
        """Latest awaiting-reply lifecycle matching subject token (RPN, load id, etc.)."""
        token = str(subject_token or "").strip()
        if not token:
            return None
        row = self._session.execute(
            text(
                """
                SELECT wl.id::text
                FROM workflow_lifecycles wl
                JOIN shipments s ON s.id = wl.shipment_id
                WHERE wl.tenant_id = CAST(:tenant_id AS uuid)
                  AND wl.workflow_name = :workflow_name
                  AND wl.sub_status = CAST(:awaiting_reply AS lifecycle_sub_status)
                  AND (
                    wl.metadata->>'reference_number' = :subject_token
                    OR wl.metadata->'appointment_payload'->>'reference_number' = :subject_token
                    OR s.metadata->>'reference_number' = :subject_token
                    OR s.metadata->>'load_id' = :subject_token
                  )
                ORDER BY wl.updated_at DESC
                LIMIT 1
                """
            ),
            {
                "tenant_id": tenant_id,
                "workflow_name": workflow_name,
                "awaiting_reply": StatusSubType.AWAITING_CUSTOMER_REPLY.value,
                "subject_token": token,
            },
        ).first()
        if row and row[0]:
            return str(row[0])
        return None
