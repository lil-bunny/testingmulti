"""Celery ingress gate: assess POD email attachments before LangGraph runs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.core.logger import get_logger
from app.domain.pod_lifecycle.guards import (
    pod_attachment_gate_eligible,
    pod_attachment_gate_skip_reason,
)
from app.domain.pod_lifecycle.settings import resolve_pod_sender_account_id
from app.domain.unipile_email import (
    attachments_metadata_from_payload,
    build_unipile_attachment_fetch_context,
)
from app.services.attachment_normalizer import AttachmentNormalizerService
from app.services.email_webhook_attachment_ingestion import (
    fetch_email_attachment_bytes_with_retry,
)
from app.services.pod_lifecycle.ingress_service import POD_EMAIL_SKIP_INVALID_ATTACHMENT

logger = get_logger(__name__)


@dataclass(frozen=True)
class PodAttachmentIngressGateResult:
    eligible: bool
    skip_reason: str | None = None
    normalization: dict[str, Any] | None = None


class PodAttachmentIngressGateService:
    """Fetch Unipile attachment bytes and assess document validity (no S3/DB)."""

    def __init__(
        self,
        *,
        normalizer: AttachmentNormalizerService | None = None,
    ) -> None:
        self._normalizer = normalizer or AttachmentNormalizerService()

    async def check(self, *, payload: dict[str, Any]) -> PodAttachmentIngressGateResult:
        attachments = attachments_metadata_from_payload(payload)
        if not attachments:
            normalization = {
                "success": False,
                "error": "No attachments provided",
            }
            return PodAttachmentIngressGateResult(
                eligible=False,
                skip_reason=pod_attachment_gate_skip_reason(normalization),
                normalization=normalization,
            )

        account_id = resolve_pod_sender_account_id(payload)
        email_id = str(payload.get("email_id") or "").strip()
        if not account_id or not email_id:
            normalization = {
                "success": False,
                "error": "attachment_fetch_failed",
            }
            logger.warning(
                "PodAttachmentIngressGateService missing fetch context email_id=%s account_id=%s",
                bool(email_id),
                bool(account_id),
            )
            return PodAttachmentIngressGateResult(
                eligible=False,
                skip_reason="attachment_fetch_failed",
                normalization=normalization,
            )

        bytes_by_id: dict[str, bytes] = {}
        for meta in attachments:
            attachment_id = str(meta.get("id") or "").strip()
            if not attachment_id:
                continue
            fetch_ctx = build_unipile_attachment_fetch_context(payload, meta)
            if not fetch_ctx.get("email_id") or not fetch_ctx.get("attachment_id"):
                continue
            try:
                file_bytes = await asyncio.to_thread(
                    fetch_email_attachment_bytes_with_retry,
                    email_id=fetch_ctx["email_id"],
                    attachment_id=fetch_ctx["attachment_id"],
                    account_id=account_id,
                )
            except Exception as exc:
                logger.warning(
                    "PodAttachmentIngressGateService fetch failed attachment_id=%s err=%s",
                    attachment_id,
                    exc,
                )
                normalization = {
                    "success": False,
                    "error": "attachment_fetch_failed",
                }
                return PodAttachmentIngressGateResult(
                    eligible=False,
                    skip_reason="attachment_fetch_failed",
                    normalization=normalization,
                )
            if file_bytes:
                bytes_by_id[attachment_id] = file_bytes

        if not bytes_by_id:
            normalization = {
                "success": False,
                "error": "attachment_fetch_failed",
            }
            return PodAttachmentIngressGateResult(
                eligible=False,
                skip_reason="attachment_fetch_failed",
                normalization=normalization,
            )

        normalization = self._normalizer.assess_attachments(
            bytes_by_id,
            shipment_number=str(payload.get("shipment_id") or "").strip() or None,
        )
        if not pod_attachment_gate_eligible(normalization):
            skip = pod_attachment_gate_skip_reason(normalization)
            if skip == "invalid_attachment":
                skip = POD_EMAIL_SKIP_INVALID_ATTACHMENT
            logger.info(
                "PodAttachmentIngressGateService skip shipment_id=%s reason=%s error=%s",
                payload.get("shipment_id"),
                skip,
                normalization.get("error"),
            )
            return PodAttachmentIngressGateResult(
                eligible=False,
                skip_reason=skip,
                normalization=normalization,
            )

        return PodAttachmentIngressGateResult(
            eligible=True,
            normalization=normalization,
        )
