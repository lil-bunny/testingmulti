"""Persist inbound/outbound channel messages in ``communications``.

Inbound: idempotent insert plus resolve existing ``communications.id`` on duplicate
``external_id``. Failures are logged and return ``None`` so webhooks and graph runs
are not blocked.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.services.communications._mapper import (
    build_email_thread_llm_user_message,
    inbound_row_from_payload,
    outbound_row_from_send,
)
from app.models.workflow_run_event_type import WorkflowRunEventType
from app.repositories.communications_repository import CommunicationsRepository
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.domain.email_thread_reply import (
    build_recipients,
    build_reply_subject,
    merge_cc,
    resolve_parent_id,
)
from app.services.unipile_service import Unipile, UnipileException

logger = get_logger(__name__)


class CommunicationsService:
    def __init__(
        self, repository: Optional[CommunicationsRepository] = None
    ) -> None:
        self._repository = repository

    def _repo(self, repos: Any) -> CommunicationsRepository:
        return self._repository or repos.communications

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

    def _find_inbound_id_by_external_id(
        self, *, tenant_id: str, external_id: str
    ) -> str | None:
        try:
            if self._repository is not None:
                return self._repository.find_id_by_tenant_and_external_id(
                    tenant_id=tenant_id,
                    external_id=external_id,
                )
            return run_with_repos(
                lambda repos: repos.communications.find_id_by_tenant_and_external_id(
                    tenant_id=tenant_id,
                    external_id=external_id,
                )
            )
        except Exception:
            logger.exception(
                "communications resolve inbound id failed external_id=%s tenant_id=%s",
                external_id,
                tenant_id,
            )
            return None

    def record_or_resolve_inbound(
        self,
        tenant_id: str,
        payload: dict[str, Any],
        *,
        extra_metadata: dict[str, Any] | None = None,
    ) -> str | None:
        """
        Persist one inbound Unipile webhook email and return ``communications.id``.

        Inserts when new; on duplicate ``external_id`` returns the existing row id.
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

        external_id = self._clean(row.get("external_id"))
        if not external_id:
            return None

        try:
            if self._repository is not None:
                comm_id = self._repository.insert(row)
            else:
                comm_id = run_with_repos(lambda repos: self._repo(repos).insert(row))
            if comm_id:
                logger.info(
                    "communications inbound recorded id=%s external_id=%s tenant_id=%s",
                    comm_id,
                    external_id,
                    tid,
                )
                return comm_id
            logger.info(
                "communications inbound duplicate skipped external_id=%s tenant_id=%s",
                external_id,
                tid,
            )
        except Exception:
            logger.exception(
                "communications inbound insert failed external_id=%s tenant_id=%s",
                external_id,
                tid,
            )

        existing_id = self._find_inbound_id_by_external_id(
            tenant_id=tid,
            external_id=external_id,
        )
        if existing_id:
            logger.info(
                "communications inbound resolved existing id=%s external_id=%s tenant_id=%s",
                existing_id,
                external_id,
                tid,
            )
        return existing_id

    def link_inbound_to_workflow_run(
        self,
        *,
        communication_id: str,
        workflow_run_id: str,
    ) -> bool:
        """Link inbound ``communications`` row to a ``workflow_runs`` id (idempotent)."""
        comm_id = self._uuid_or_none(communication_id, field_name="communication_id")
        run_id = self._uuid_or_none(workflow_run_id, field_name="workflow_run_id")
        if not comm_id or not run_id:
            return False
        try:
            if self._repository is not None:
                linked = self._repository.link_workflow_run(
                    communication_id=comm_id,
                    workflow_run_id=run_id,
                )
            else:
                linked = run_with_repos(
                    lambda repos: repos.communications.link_workflow_run(
                        communication_id=comm_id,
                        workflow_run_id=run_id,
                    )
                )
            if linked:
                logger.info(
                    "communications linked to workflow_run comm_id=%s run_id=%s",
                    comm_id,
                    run_id,
                )
            return linked
        except Exception:
            logger.exception(
                "communications link to workflow_run failed comm_id=%s run_id=%s",
                comm_id,
                run_id,
            )
            return False

    def resolve_thread_for_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.EMAIL_RECEIVED,
    ) -> str | None:
        """Resolve email thread from communications linked to lifecycle inbound runs."""
        tid = self._tenant_uuid_or_none(tenant_id)
        lid = self._uuid_or_none(workflow_lifecycle_id, field_name="workflow_lifecycle_id")
        if not tid or not lid:
            return None
        try:
            if self._repository is not None:
                thread = self._repository.find_inbound_thread_for_lifecycle(
                    tenant_id=tid,
                    workflow_lifecycle_id=lid,
                    anchor_event_type=anchor_event_type,
                )
            else:
                thread = run_with_repos(
                    lambda repos: repos.communications.find_inbound_thread_for_lifecycle(
                        tenant_id=tid,
                        workflow_lifecycle_id=lid,
                        anchor_event_type=anchor_event_type,
                    )
                )
            if not thread:
                return None
            return str(thread).strip() or None
        except Exception:
            logger.exception(
                "communications resolve_thread_for_lifecycle failed tenant_id=%s lifecycle_id=%s",
                tid,
                lid,
            )
            return False


    def find_active_lifecycle_id_for_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_name: str = "driver_assignment",
    ) -> str | None:
        """Active (non-terminal) lifecycle for ``workflow_name`` on an email thread."""
        tid = self._tenant_uuid_or_none(tenant_id)
        th = self._clean(thread_id)
        if not tid or not th:
            return None
        try:
            if self._repository is not None:
                lifecycle_id = self._repository.find_active_lifecycle_id_for_thread(
                    tenant_id=tid,
                    thread_id=th,
                    workflow_name=workflow_name,
                )
            else:
                lifecycle_id = run_with_repos(
                    lambda repos: repos.communications.find_active_lifecycle_id_for_thread(
                        tenant_id=tid,
                        thread_id=th,
                        workflow_name=workflow_name,
                    )
                )
            return lifecycle_id
        except Exception:
            logger.exception(
                "communications find_active_lifecycle_id_for_thread failed "
                "tenant_id=%s thread_id=%s workflow_name=%s",
                tid,
                th,
                workflow_name,
            )
            return None

    def resolve_lifecycle_id_for_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_name: str = "load_tendering",
    ) -> str | None:
        """Thread → lifecycle via earliest patched comm + ``workflow_runs`` join."""
        tid = self._tenant_uuid_or_none(tenant_id)
        th = self._clean(thread_id)
        if not tid or not th:
            return None
        try:
            if self._repository is not None:
                lifecycle_id = self._repository.resolve_lifecycle_id_for_thread(
                    tenant_id=tid,
                    thread_id=th,
                    workflow_name=workflow_name,
                )
            else:
                lifecycle_id = run_with_repos(
                    lambda repos: repos.communications.resolve_lifecycle_id_for_thread(
                        tenant_id=tid,
                        thread_id=th,
                        workflow_name=workflow_name,
                    )
                )
            return lifecycle_id
        except Exception:
            logger.exception(
                "communications resolve_lifecycle_id_for_thread failed tenant_id=%s thread_id=%s",
                tid,
                th,
            )
            return None

    def find_shipment_context_for_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
    ) -> list[dict[str, Any]]:
        """Thread → lifecycles with ``shipments.id`` FK, newest per shipment."""
        tid = self._tenant_uuid_or_none(tenant_id)
        th = self._clean(thread_id)
        if not tid or not th:
            return []
        try:
            if self._repository is not None:
                return self._repository.find_shipment_context_for_thread(
                    tenant_id=tid,
                    thread_id=th,
                )
            return run_with_repos(
                lambda repos: repos.communications.find_shipment_context_for_thread(
                    tenant_id=tid,
                    thread_id=th,
                )
            )
        except Exception:
            logger.exception(
                "communications find_shipment_context_for_thread failed tenant_id=%s thread_id=%s",
                tid,
                th,
            )
            return []

    def is_thread_linked_to_lifecycle(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
    ) -> bool:
        tid = self._tenant_uuid_or_none(tenant_id)
        th = self._clean(thread_id)
        lid = self._uuid_or_none(workflow_lifecycle_id, field_name="workflow_lifecycle_id")
        if not tid or not th or not lid:
            return False
        try:
            if self._repository is not None:
                return self._repository.is_thread_linked_to_lifecycle(
                    tenant_id=tid,
                    thread_id=th,
                    workflow_lifecycle_id=lid,
                    anchor_event_type=anchor_event_type,
                )
            return run_with_repos(
                lambda repos: repos.communications.is_thread_linked_to_lifecycle(
                    tenant_id=tid,
                    thread_id=th,
                    workflow_lifecycle_id=lid,
                    anchor_event_type=anchor_event_type,
                )
            )
        except Exception:
            logger.exception(
                "communications is_thread_linked_to_lifecycle failed tenant_id=%s thread_id=%s",
                tid,
                th,
            )
            return False

    def find_linked_thread_for_lifecycle(
        self,
        *,
        tenant_id: str,
        workflow_lifecycle_id: str,
        anchor_event_type: WorkflowRunEventType = WorkflowRunEventType.CARRIER_EMAIL_RECEIVED,
    ) -> str | None:
        tid = self._tenant_uuid_or_none(tenant_id)
        lid = self._uuid_or_none(workflow_lifecycle_id, field_name="workflow_lifecycle_id")
        if not tid or not lid:
            return None
        try:
            if self._repository is not None:
                thread = self._repository.find_linked_thread_for_lifecycle(
                    tenant_id=tid,
                    workflow_lifecycle_id=lid,
                    anchor_event_type=anchor_event_type,
                )
            else:
                thread = run_with_repos(
                    lambda repos: repos.communications.find_linked_thread_for_lifecycle(
                        tenant_id=tid,
                        workflow_lifecycle_id=lid,
                        anchor_event_type=anchor_event_type,
                    )
                )
            if not thread:
                return None
            return str(thread).strip() or None
        except Exception:
            logger.exception(
                "communications find_linked_thread_for_lifecycle failed tenant_id=%s lifecycle_id=%s",
                tid,
                lid,
            )
            return None

    def link_workflow_run_to_thread(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        workflow_run_id: str,
    ) -> int:
        tid = self._tenant_uuid_or_none(tenant_id)
        th = self._clean(thread_id)
        run_id = self._uuid_or_none(workflow_run_id, field_name="workflow_run_id")
        if not tid or not th or not run_id:
            return 0
        try:
            if self._repository is not None:
                patched = self._repository.link_workflow_run_to_thread(
                    tenant_id=tid,
                    thread_id=th,
                    workflow_run_id=run_id,
                )
            else:
                patched = run_with_repos(
                    lambda repos: repos.communications.link_workflow_run_to_thread(
                        tenant_id=tid,
                        thread_id=th,
                        workflow_run_id=run_id,
                    )
                )
            if patched:
                logger.info(
                    "communications patched workflow_run on thread tenant_id=%s thread_id=%s "
                    "run_id=%s count=%s",
                    tid,
                    th,
                    run_id,
                    patched,
                )
            return patched
        except Exception:
            logger.exception(
                "communications link_workflow_run_to_thread failed tenant_id=%s thread_id=%s",
                tid,
                th,
            )
            return 0

    def find_outbound_id_by_idempotency_key(
        self,
        *,
        tenant_id: str,
        idempotency_key: str,
        channel: str | None = None,
    ) -> str | None:
        """Lookup a prior outbound alert row by idempotency metadata."""
        tid = self._tenant_uuid_or_none(tenant_id)
        key = self._clean(idempotency_key)
        if not tid or not key:
            return None
        try:
            if self._repository is not None:
                return self._repository.find_outbound_id_by_idempotency_key(
                    tenant_id=tid,
                    idempotency_key=key,
                    channel=channel,
                )
            return run_with_repos(
                lambda repos: repos.communications.find_outbound_id_by_idempotency_key(
                    tenant_id=tid,
                    idempotency_key=key,
                    channel=channel,
                )
            )
        except Exception:
            logger.exception(
                "communications idempotency lookup failed tenant_id=%s key=%s",
                tid,
                key,
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
            if self._repository is not None:
                comm_id = self._repository.insert(row)
            else:
                comm_id = run_with_repos(lambda repos: self._repo(repos).insert(row))
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

    def send_thread_reply(
        self,
        *,
        tenant_id: str,
        thread_id: str,
        body: str,
        account_id: str,
        subject: str | None = None,
        reply_to_message_id: str | None = None,
        cc: list[dict[str, Any]] | None = None,
        communication_metadata: dict[str, Any] | None = None,
        workflow_run_id: str | None = None,
    ) -> dict[str, Any]:
        """Unipile thread reply-all + outbound ``communications`` row."""
        th = self._clean(thread_id)
        acc = self._clean(account_id)
        if not th:
            raise UnipileException("thread_id is required to reply to a thread")
        if not acc:
            raise UnipileException("account_id is required to reply to a thread")

        unipile = Unipile()
        exclude_email = unipile.get_account_email(acc)
        emails_result = unipile.list_emails(account_id=acc, thread_id=th, limit=50)
        emails = emails_result.get("items", []) if isinstance(emails_result, dict) else []
        if not emails:
            raise UnipileException(f"No emails found for thread_id={th}")

        sorted_emails = sorted(emails, key=lambda e: e.get("date") or "", reverse=True)
        latest_email = sorted_emails[0]
        reply_to_id = resolve_parent_id(
            unipile, latest_email, reply_to_message_id, acc
        )
        logger.info("send_thread_reply: resolved reply_to_id=%s", reply_to_id)

        original_subject = (latest_email.get("subject") or "").strip()
        effective_subject = build_reply_subject(original_subject, subject)
        to_list, thread_cc = build_recipients(latest_email, exclude_email)
        if not to_list:
            raise UnipileException("Could not determine reply recipients from the thread")
        cc_final = merge_cc(thread_cc, cc, exclude_email, to_list)

        result = unipile.send_email(
            to=to_list,
            subject=effective_subject,
            body=body,
            account_id=acc,
            reply_to=reply_to_id,
            cc=cc_final,
        )
        result.setdefault("thread_id", th)
        result.setdefault("reply_to_message_id", reply_to_id)
        if not result.get("success", True):
            logger.warning(
                "send_thread_reply: Unipile send failed thread_id=%s reply_to_id=%s err=%s",
                th,
                reply_to_id,
                result.get("error"),
            )
            return result

        comm_id = self.record_outbound_from_send(
            tenant_id,
            send_result=result,
            body=body,
            subject=effective_subject,
            thread_id=th,
            to=to_list,
            cc=cc_final,
            account_id=acc,
            extra_metadata=communication_metadata,
            workflow_run_id=workflow_run_id,
        )
        if comm_id:
            result["communication_id"] = comm_id
        return result

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
            if self._repository is not None:
                rows = self._repository.list_email_thread(
                    tenant_id=tid,
                    thread_id=tid_s,
                    limit=limit,
                )
            else:
                rows = run_with_repos(
                    lambda repos: self._repo(repos).list_email_thread(
                        tenant_id=tid,
                        thread_id=tid_s,
                        limit=limit,
                    )
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
