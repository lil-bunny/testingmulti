"""POD attachment pipeline: pre-graph assess + in-graph merge/upload."""

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
    """Outcome of assess or merge/upload."""

    success: bool
    skip_reason: str | None = None
    state_patch: dict[str, Any] | None = None
    stage_dir: str | None = None


class PodAttachmentPipelineService:
    """
    POD attachments in two phases:

    1. Pre-graph assess: fetch → classify → stage local sources (no S3 merge upload).
    2. In-graph merge/upload: merge staged files → S3 → ``documents`` row.
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
        tenant_settings = payload.get("tenant_settings")
        if isinstance(tenant_settings, dict):
            meta["tenant_settings"] = tenant_settings
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

    def _assess_patch(
        self,
        *,
        normalization: dict[str, Any],
        stage_dir: Path,
    ) -> PodAttachmentPipelineResult:
        """Build state patch after successful classify+stage (no merged S3 key yet)."""
        merge_paths = [
            str(p).strip()
            for p in (normalization.get("pod_merge_source_paths") or [])
            if str(p).strip()
        ]
        vision_paths = [
            str(p).strip()
            for p in (normalization.get("pod_vision_image_paths") or [])
            if str(p).strip()
        ]
        if not merge_paths:
            shutil.rmtree(stage_dir, ignore_errors=True)
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason=POD_EMAIL_SKIP_INVALID_ATTACHMENT,
                state_patch={"attachment_normalization": normalization},
            )

        patch: dict[str, Any] = {
            "attachment_normalization": normalization,
            "pod_merge_source_paths": merge_paths,
            "pod_vision_image_paths": vision_paths,
            "pod_source_object_keys": self._source_object_keys(normalization),
            "has_attachments": True,
            "pod_attachment_stage_dir": str(stage_dir),
        }
        logger.info(
            "attachment.pipeline.assess.done success=true sources=%s vision=%s",
            len(merge_paths),
            len(vision_paths),
        )
        return PodAttachmentPipelineResult(
            success=True,
            state_patch=patch,
            stage_dir=str(stage_dir),
        )

    def merge_and_upload_from_state(
        self,
        data: dict[str, Any],
    ) -> PodAttachmentPipelineResult:
        """In-graph: merge staged local sources, upload to S3, persist ``documents``."""
        merge_paths = [
            str(p).strip()
            for p in (data.get("pod_merge_source_paths") or [])
            if str(p).strip()
        ]
        stage_dir_raw = str(data.get("pod_attachment_stage_dir") or "").strip()
        stage_dir = Path(stage_dir_raw) if stage_dir_raw else None
        shipment_number = str(data.get("shipment_id") or "").strip() or None
        shipments_row_id = str(data.get("shipments_row_id") or "").strip() or None

        if not merge_paths:
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason="attachment_normalization_failed",
                state_patch={
                    "attachment_normalization": {
                        **(data.get("attachment_normalization") or {}),
                        "success": False,
                        "error": "No staged source paths provided",
                    }
                },
            )

        if stage_dir is None:
            stage_dir = self._build_stage_dir(data)
            stage_dir.mkdir(parents=True, exist_ok=True)

        local_merged_path = str(stage_dir / pod_merged_filename(shipment_number))
        normalization_prior = data.get("attachment_normalization") or {}
        source_ids = list(normalization_prior.get("source_attachment_ids") or [])

        logger.info(
            "attachment.pipeline.merge.start shipment_id=%s sources=%s",
            shipment_number,
            len(merge_paths),
        )
        merged = self._normalizer.merge_and_upload_staged(
            merge_paths,
            shipment_number=shipment_number,
            local_merged_path=local_merged_path,
            source_attachment_ids=source_ids,
        )
        object_key = str(merged.get("pod_merged_pdf_object_key") or "").strip()
        if not merged.get("success") or not object_key:
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason="attachment_normalization_failed",
                state_patch={
                    "attachment_normalization": {
                        **normalization_prior,
                        "success": False,
                        "error": merged.get("error") or "PDF merge failed",
                    }
                },
            )

        source_keys = self._source_object_keys(normalization_prior) or [
            str(p) for p in merge_paths
        ]
        persist = insert_document(
            DocumentType.POD,
            storage_key=object_key,
            shipments_row_id=shipments_row_id,
            metadata={"source_object_keys": source_keys},
        )
        local_merged = str(merged.get("pod_merged_local_path") or "").strip()
        patch: dict[str, Any] = {
            "attachment_normalization": {
                **normalization_prior,
                "success": True,
                "pod_merged_pdf_object_key": object_key,
                "assess_only": False,
                "error": None,
            },
            "pod_merged_pdf_object_key": object_key,
            "pod_object_keys": [object_key],
            "pod_source_object_keys": source_keys,
            "has_attachments": True,
            "documents_pod": persist,
            "pod_attachment_stage_dir": str(stage_dir),
        }
        if local_merged:
            patch["pod_merged_local_path"] = local_merged
        if data.get("pod_vision_image_paths"):
            patch["pod_vision_image_paths"] = list(data["pod_vision_image_paths"])
        if data.get("pod_merge_source_paths"):
            patch["pod_merge_source_paths"] = list(data["pod_merge_source_paths"])

        logger.info(
            "attachment.pipeline.merge.done success=true merged=%s documents_stored=%s",
            object_key,
            persist.get("stored"),
        )
        return PodAttachmentPipelineResult(
            success=True,
            state_patch=patch,
            stage_dir=str(stage_dir),
        )

    async def run_for_email_payload(
        self,
        *,
        payload: dict[str, Any],
    ) -> PodAttachmentPipelineResult:
        """Fetch Unipile attachments, classify, stage local files (no S3 merge)."""
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

        logger.info(
            "attachment.pipeline.assess.start source=email shipment_id=%s attachments=%s",
            shipment_number,
            len(bytes_by_id),
        )
        normalization = self._normalizer.normalize_from_bytes(
            bytes_by_id,
            shipment_number=shipment_number,
            upload_merged=False,
            stage_dir=str(stage_dir),
            trace_metadata=self._classifier_trace_metadata(payload),
        )

        if not pod_attachment_gate_eligible(normalization):
            shutil.rmtree(stage_dir, ignore_errors=True)
            skip = pod_attachment_gate_skip_reason(normalization)
            if skip == "invalid_attachment":
                skip = POD_EMAIL_SKIP_INVALID_ATTACHMENT
            logger.info(
                "attachment.pipeline.assess.done source=email eligible=false reason=%s",
                skip,
            )
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason=skip,
                state_patch={"attachment_normalization": normalization},
            )

        return self._assess_patch(normalization=normalization, stage_dir=stage_dir)

    def run_for_object_keys(
        self,
        *,
        pod_object_keys: list[str],
        shipment_id: str | None,
        shipments_row_id: str | None,
        stage_token: str | None = None,
        trace_payload: dict[str, Any] | None = None,
    ) -> PodAttachmentPipelineResult:
        """Classify + stage from S3 object keys (manual fresh upload); no merge yet."""
        del shipments_row_id  # used only at in-graph merge/persist time
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

        logger.info(
            "attachment.pipeline.assess.start source=object_keys shipment_id=%s keys=%s",
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
            upload_merged=False,
            stage_dir=str(stage_dir),
            trace_metadata=self._classifier_trace_metadata(correlation),
        )
        if not pod_attachment_gate_eligible(normalization):
            shutil.rmtree(stage_dir, ignore_errors=True)
            skip = pod_attachment_gate_skip_reason(normalization)
            if skip == "invalid_attachment":
                skip = POD_EMAIL_SKIP_INVALID_ATTACHMENT
            return PodAttachmentPipelineResult(
                success=False,
                skip_reason=skip or POD_EMAIL_SKIP_INVALID_ATTACHMENT,
                state_patch={"attachment_normalization": normalization},
            )
        return self._assess_patch(normalization=normalization, stage_dir=stage_dir)
