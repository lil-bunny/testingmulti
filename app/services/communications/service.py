"""Persist inbound/outbound channel messages in ``communications``.

Failures are logged and return ``None`` so webhooks and graph runs are not blocked.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from app.core.logger import get_logger
from app.services.communications._mapper import (
    build_email_thread_llm_user_message,
    inbound_row_from_payload,
    outbound_row_from_send,
)
from app.repositories.communications_repository import CommunicationsRepository
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid

logger = get_logger(__name__)


class CommunicationsService:
    def __init__(
        self, repository: Optional[CommunicationsRepository] = None
    ) -> None:
        self._repository = repository or CommunicationsRepository()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def _uuid_or_none(value: Any, *, field_name: str) -> str | None:
        raw = CommunicationsService._clean(value)
        if not raw:
            return None
        try:
            return str(uuid.UUID(raw))
        except (ValueError, AttributeError):
            logger.warning(
                "communications skipped invalid %s=%r (expected UUID)",
                field_name,
                value,
            )
            return None

    def _tenant_uuid_or_none(self, tenant_id: str | None) -> str | None:
        """Accept tenants.id UUID or graph slug (e.g. gelita)."""
        raw = self._clean(tenant_id)
        if not raw:
            return None
        resolved = resolve_graph_tenant_to_uuid(raw)
        return resolved or raw

    def record_inbound(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        *,
        extra_metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Log one inbound Unipile webhook email.

        ``tenant_id`` should be ``tenants.id`` (UUID) from webhook tenant resolution.
        """
        tid = self._tenant_uuid_or_none(tenant_id)
        if not tid:
            logger.warning(
                "communications inbound skipped: invalid tenant_id=%r",
                tenant_id,
            )
            return None

        row = inbound_row_from_payload(
            payload,
            tenant_id=tid,
            extra_metadata=extra_metadata,
        )
        if not row:
            logger.warning(
                "communications inbound skipped: missing email_id tenant_id=%s",
                tid,
            )
            return None

        try:
            comm_id = self._repository.insert(row)
            if comm_id:
                logger.info(
                    "communications inbound recorded id=%s external_id=%s tenant_id=%s",
                    comm_id,
                    row.get("external_id"),
                    tid,
                )
            else:
                logger.info(
                    "communications inbound duplicate skipped external_id=%s tenant_id=%s",
                    row.get("external_id"),
                    tid,
                )
            return comm_id
        except Exception:
            logger.exception(
                "communications inbound insert failed external_id=%s tenant_id=%s",
                row.get("external_id"),
                tid,
            )
            return None

    def record_outbound_from_send(
        self,
        tenant_id: str,
        *,
        send_result: dict[str, Any],
        body: str,
        subject: str | None = None,
        thread_id: str | None = None,
        to: Any = None,
        cc: Any = None,
        bcc: Any = None,
        account_id: str | None = None,
        extra_metadata: dict[str, Any] | None = None,
        workflow_run_id: str | None = None,
    ) -> str | None:
        """Log one successful outbound email (Unipile send result)."""
        tid = self._tenant_uuid_or_none(tenant_id)
        if not tid:
            logger.warning(
                "communications outbound skipped: invalid tenant_id=%r",
                tenant_id,
            )
            return None

        run_id = self._uuid_or_none(workflow_run_id, field_name="workflow_run_id")

        row = outbound_row_from_send(
            tenant_id=tid,
            send_result=send_result,
            body=body,
            subject=subject,
            thread_id=thread_id,
            to=to,
            cc=cc,
            bcc=bcc,
            account_id=account_id,
            extra_metadata=extra_metadata,
            workflow_run_id=run_id,
        )
        if not row:
            if send_result.get("success"):
                logger.warning(
                    "communications outbound skipped: no tracking id tenant_id=%s",
                    tid,
                )
            return None

        try:
            comm_id = self._repository.insert(row)
            if comm_id:
                logger.info(
                    "communications outbound recorded id=%s external_id=%s tenant_id=%s",
                    comm_id,
                    row.get("external_id"),
                    tid,
                )
            else:
                logger.info(
                    "communications outbound duplicate skipped external_id=%s tenant_id=%s",
                    row.get("external_id"),
                    tid,
                )
            return comm_id
        except Exception:
            logger.exception(
                "communications outbound insert failed external_id=%s tenant_id=%s",
                row.get("external_id"),
                tid,
            )
            return None

    def list_thread_messages(
        self,
        tenant_id: str,
        thread_id: str,
        *,
        channel: str = "email",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """
        List stored messages for an email thread (oldest first). Tenant-agnostic.

        ``tenant_id`` may be ``tenants.id`` UUID or graph slug.
        """
        tid = self._tenant_uuid_or_none(tenant_id)
        tid_s = self._clean(thread_id)
        if not tid or not tid_s:
            logger.warning(
                "communications list_thread_messages skipped: tenant_id=%r thread_id=%r",
                tenant_id,
                thread_id,
            )
            return []
        if channel != "email":
            logger.warning(
                "communications list_thread_messages: unsupported channel=%r",
                channel,
            )
            return []

        try:
            rows = self._repository.list_email_thread(
                tenant_id=tid,
                thread_id=tid_s,
                limit=limit,
            )
            logger.info(
                "communications list_thread_messages tenant_id=%s thread_id=%s count=%s",
                tid,
                tid_s,
                len(rows),
            )
            return rows
        except Exception:
            logger.exception(
                "communications list_thread_messages failed tenant_id=%s thread_id=%s",
                tid,
                tid_s,
            )
            return []

    def build_thread_llm_user_message(
        self,
        tenant_id: str,
        thread_id: str,
        *,
        fallback_body: str | None = None,
        limit: int = 50,
        max_messages: int | None = None,
    ) -> tuple[str, int]:
        """
        Chronological ``email N`` LLM user text from ``communications``, with webhook fallback.
        """
        messages = self.list_thread_messages(tenant_id, thread_id, limit=limit)
        text = build_email_thread_llm_user_message(
            messages,
            fallback_body=fallback_body,
            max_messages=max_messages,
        )
        return text, len(messages)
