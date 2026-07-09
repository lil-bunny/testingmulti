"""Pre-graph POD attachment pipeline: fetch/classify/merge/upload/persist once."""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
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
from app.models.document import DocumentType
from app.services.attachment_normalizer import (
    AttachmentNormalizerService,
    pod_merged_filename,
)
from app.services.email_webhook_attachment_ingestion import (
    fetch_email_attachment_bytes_with_retry,
)
from app.services.pod_lifecycle.ingress_service import POD_EMAIL_SKIP_INVALID_ATTACHMENT
from app.tools.documents import insert_document

logger = get_logger(__name__)


@dataclass(frozen=True)
class PodAttachmentPipelineResult:
    """Outcome of the single pre-graph attachment pipeline."""

    success: bool
    skip_reason: str | None = None
    state_patch: dict[str, Any] | None = None
    stage_dir: str | None = None


class PodAttachmentPipelineService:
    """
    One path for POD attachments before LangGraph:

    load inputs → classify → merge → upload merged PDF → persist ``documents`` row.
    """

    def __init__(
        self,
        *,
        normalizer: AttachmentNormalizerService | None = None,
    ) -> None:
        self._normalizer = normalizer or AttachmentNormalizerService()

    @staticmethod
    def _stage_root_token(payload: dict[str, Any]) -> str:
        token = (
            str(payload.get("workflow_lifecycle_id") or "").strip()
            or str(payload.get("execution_id") or "").strip()
            or str(payload.get("email_id") or "").strip()
            or str(payload.get("shipment_id") or "").strip()
            or "pod"
        )
        return "".join(c if c.isalnum() or c in "-_." else "_" for c in token)[:120]

    def _build_stage_dir(self, payload: dict[str, Any]) -> Path:
        return Path(settings.POD_ATTACHMENT_STAGE_ROOT) / (
            f"pod_{self._stage_root_token(payload)}"
        )

    @staticmethod
    def _classifier_trace_metadata(payload: dict[str, Any]) -> dict[str, Any]:
        """Minimal LangSmith correlation keys for linking classifier spans to workflows."""
        meta: dict[str, Any] = {
            "workflow_name": "pod_lifecycle",
            "step_key": "pod_attachment_classifier",
            "classify_context": "attachment_pipeline",
        }
        for key in (
            "execution_id",
            "workflow_lifecycle_id",
            "tenant_id",
            "tenant_slug",
            "shipment_id",
        ):
            value = str(payload.get(key) or "").strip()
            if value:
                meta[key] = value
        return meta

    @staticmethod
    def _source_object_keys(normalization: dict[str, Any]) -> list[str]:
        cleanup = normalization.get("source_attachments_cleanup") or {}
        keys: list[str] = []
        for item in cleanup.get("valid_source") or []:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("attachment_ref") or "").strip()
            if ref:
                keys.append(ref)
        return keys

    def _persist_and_patch(
        self,
        *,
        normalization: dict[str, Any],
        shipments_row_id: str | None,
        stage_dir: Path | None,
    ) -> PodAttachmentPipelineResult:
        merged = str(normalization.get("pod_merged_pdf_object_key") or "").strip()
        if not normalization.get("success") or not merged:
            if stage_dir is not None:
                shutil.rmtree(stage_dir, ignore_errors=True)
            skip = pod_attachment_gate_skip_reason(normalization)
            if skip == "invalid_attachment":
                skip = POD_EMAIL_SKIP_INVALID_ATTACHMENT
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason=skip or POD_EMAIL_SKIP_INVALID_ATTACHMENT,
                state_patch={"attachment_normalization": normalization},
            )

        source_keys = self._source_object_keys(normalization)
        persist = insert_document(
            DocumentType.POD,
            storage_key=merged,
            shipments_row_id=shipments_row_id,
            metadata={"source_object_keys": source_keys},
        )
        local_merged = str(normalization.get("pod_merged_local_path") or "").strip()
        patch: dict[str, Any] = {
            "attachment_normalization": normalization,
            "pod_merged_pdf_object_key": merged,
            "pod_object_keys": [merged],
            "pod_source_object_keys": source_keys,
            "has_attachments": True,
            "documents_pod": persist,
        }
        if local_merged:
            patch["pod_merged_local_path"] = local_merged
        if stage_dir is not None:
            patch["pod_attachment_stage_dir"] = str(stage_dir)

        logger.info(
            "attachment.pipeline.done success=true merged=%s documents_stored=%s source_keys=%s",
            merged,
            persist.get("stored"),
            len(source_keys),
        )
        return PodAttachmentPipelineResult(
            success=True,
            state_patch=patch,
            stage_dir=str(stage_dir) if stage_dir is not None else None,
        )

    async def run_for_email_payload(
        self,
        *,
        payload: dict[str, Any],
    ) -> PodAttachmentPipelineResult:
        """Fetch Unipile attachments, classify/merge/upload, persist POD document."""
        attachments = attachments_metadata_from_payload(payload)
        if not attachments:
            normalization = {"success": False, "error": "No attachments provided"}
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason=pod_attachment_gate_skip_reason(normalization),
                state_patch={"attachment_normalization": normalization},
            )

        account_id = resolve_pod_sender_account_id(payload)
        email_id = str(payload.get("email_id") or "").strip()
        if not account_id or not email_id:
            normalization = {"success": False, "error": "attachment_fetch_failed"}
            logger.warning(
                "attachment.pipeline missing fetch context email_id=%s account_id=%s",
                bool(email_id),
                bool(account_id),
            )
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason="attachment_fetch_failed",
                state_patch={"attachment_normalization": normalization},
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
                    "attachment.pipeline fetch failed attachment_id=%s err=%s",
                    attachment_id,
                    exc,
                )
                normalization = {"success": False, "error": "attachment_fetch_failed"}
                return PodAttachmentPipelineResult(
                    success=False,
                    skip_reason="attachment_fetch_failed",
                    state_patch={"attachment_normalization": normalization},
                )
            if file_bytes:
                bytes_by_id[attachment_id] = file_bytes

        if not bytes_by_id:
            normalization = {"success": False, "error": "attachment_fetch_failed"}
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason="attachment_fetch_failed",
                state_patch={"attachment_normalization": normalization},
            )

        shipment_number = str(payload.get("shipment_id") or "").strip() or None
        stage_dir = self._build_stage_dir(payload)
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        stage_dir.mkdir(parents=True, exist_ok=True)
        local_merged_path = str(stage_dir / pod_merged_filename(shipment_number))

        logger.info(
            "attachment.pipeline.start source=email shipment_id=%s attachments=%s",
            shipment_number,
            len(bytes_by_id),
        )
        normalization = self._normalizer.normalize_from_bytes(
            bytes_by_id,
            shipment_number=shipment_number,
            upload_merged=True,
            local_merged_path=local_merged_path,
            trace_metadata=self._classifier_trace_metadata(payload),
        )

        if not pod_attachment_gate_eligible(normalization):
            shutil.rmtree(stage_dir, ignore_errors=True)
            skip = pod_attachment_gate_skip_reason(normalization)
            if skip == "invalid_attachment":
                skip = POD_EMAIL_SKIP_INVALID_ATTACHMENT
            logger.info(
                "attachment.pipeline.done source=email eligible=false reason=%s",
                skip,
            )
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason=skip,
                state_patch={"attachment_normalization": normalization},
            )

        return self._persist_and_patch(
            normalization=normalization,
            shipments_row_id=str(payload.get("shipments_row_id") or "").strip() or None,
            stage_dir=stage_dir,
        )

    def run_for_object_keys(
        self,
        *,
        pod_object_keys: list[str],
        shipment_id: str | None,
        shipments_row_id: str | None,
        stage_token: str | None = None,
        trace_payload: dict[str, Any] | None = None,
    ) -> PodAttachmentPipelineResult:
        """Classify/merge/upload from S3 object keys (manual fresh upload)."""
        keys = [str(k).strip() for k in pod_object_keys if str(k).strip()]
        if not keys:
            normalization = {"success": False, "error": "No pod_object_keys provided"}
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason=pod_attachment_gate_skip_reason(normalization),
                state_patch={"attachment_normalization": normalization},
            )

        payload_for_stage = {
            "shipment_id": shipment_id,
            "execution_id": stage_token,
        }
        stage_dir = self._build_stage_dir(payload_for_stage)
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        stage_dir.mkdir(parents=True, exist_ok=True)
        local_merged_path = str(stage_dir / pod_merged_filename(shipment_id))

        logger.info(
            "attachment.pipeline.start source=object_keys shipment_id=%s keys=%s",
            shipment_id,
            len(keys),
        )
        correlation = dict(trace_payload or {})
        if shipment_id and not correlation.get("shipment_id"):
            correlation["shipment_id"] = shipment_id
        if stage_token and not correlation.get("execution_id"):
            correlation["execution_id"] = stage_token
        normalization = self._normalizer.normalize(
            keys,
            shipment_number=shipment_id,
            upload_merged=True,
            local_merged_path=local_merged_path,
            trace_metadata=self._classifier_trace_metadata(correlation),
        )
        return self._persist_and_patch(
            normalization=normalization,
            shipments_row_id=shipments_row_id,
            stage_dir=stage_dir,
        )
