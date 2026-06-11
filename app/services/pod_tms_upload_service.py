"""POD PDF staging helpers for manual upload ingress and workflow nodes."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from app.core.config import settings
from app.core.logger import get_logger
from app.models.document import DocumentType
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from app.services.attachment_normalizer import pod_individual_attachment_filename
from app.services.s3bucket_service import S3Bucket
from app.services.shipments_service import ShipmentsService
from app.services.workflow_lifecycle_service import WorkflowLifecycleService
from app.tools.documents import insert_document

logger = get_logger(__name__)

POD_LIFECYCLE_WORKFLOW = "pod_lifecycle"
PDF_MAGIC = b"%PDF"
MAX_POD_PDF_BYTES = 25 * 1024 * 1024


class PodLifecycleNotFoundError(Exception):
    """Raised when no ``pod_lifecycle`` row exists for the shipment."""


@dataclass(frozen=True)
class PodAttachmentStageResult:
    object_key: str
    document_id: str | None
    attachment_id: str


@dataclass(frozen=True)
class PodLifecycleResolution:
    tenant_uuid: str
    shipment_number: str
    shipments_row_id: str
    workflow_lifecycle_id: str


class PodTmsUploadService:
    def __init__(
        self,
        *,
        lifecycle_service: WorkflowLifecycleService | None = None,
        shipments_service: ShipmentsService | None = None,
        s3_bucket: S3Bucket | None = None,
    ) -> None:
        self._lifecycle = lifecycle_service or WorkflowLifecycleService()
        self._shipments = shipments_service or ShipmentsService()
        self._s3 = s3_bucket or S3Bucket()

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        s = str(value).strip()
        return s if s else None

    @staticmethod
    def validate_pdf(pdf_bytes: bytes) -> None:
        if not pdf_bytes:
            raise ValueError("PDF file is empty")
        if len(pdf_bytes) > MAX_POD_PDF_BYTES:
            raise ValueError(f"PDF exceeds maximum size of {MAX_POD_PDF_BYTES} bytes")
        if not pdf_bytes.startswith(PDF_MAGIC):
            raise ValueError("File is not a valid PDF")

    def resolve_pod_lifecycle(
        self,
        *,
        tenant_slug: str,
        shipment_id: str,
    ) -> PodLifecycleResolution:
        """Resolve ``pod_lifecycle`` for ``shipments.id`` (UUID primary key)."""
        ship_uuid = self._clean(shipment_id)
        slug = self._clean(tenant_slug)
        if not ship_uuid or not slug:
            raise ValueError("shipment_id and tenant_slug are required")

        tenant_uuid = resolve_graph_tenant_to_uuid(slug)
        if not tenant_uuid:
            raise PodLifecycleNotFoundError("unknown tenant")

        ship_row = self._shipments.get_by_id(
            tenant_id=tenant_uuid,
            shipment_id=ship_uuid,
        )
        if not ship_row:
            raise PodLifecycleNotFoundError("shipment not found")

        ship_uuid = self._clean(ship_row.get("id"))
        if not ship_uuid:
            raise PodLifecycleNotFoundError("shipment not found")

        shipment_number = self._clean(ship_row.get("shipment_number"))
        if not shipment_number:
            raise PodLifecycleNotFoundError("shipment not found")

        lc = self._lifecycle.read_lifecycle(
            tenant_id=slug,
            workflow_name=POD_LIFECYCLE_WORKFLOW,
            shipment_id=ship_uuid,
        )
        if not lc.get("found") or not lc.get("lifecycle_id"):
            raise PodLifecycleNotFoundError("pod_lifecycle not found for shipment")

        return PodLifecycleResolution(
            tenant_uuid=tenant_uuid,
            shipment_number=shipment_number,
            shipments_row_id=ship_uuid,
            workflow_lifecycle_id=str(lc["lifecycle_id"]),
        )

    def stage_pod_attachment(
        self,
        *,
        pdf_bytes: bytes,
        shipment_id: str,
        shipments_row_id: str | None = None,
        filename: str | None = None,
    ) -> PodAttachmentStageResult:
        """Upload PDF to S3 and persist a ``pod_attachment`` documents row."""
        self.validate_pdf(pdf_bytes)
        ship_token = self._clean(shipment_id) or "unknown"
        attachment_id = f"manual-{uuid.uuid4().hex[:12]}"
        s3_filename = (
            self._clean(filename)
            or pod_individual_attachment_filename(attachment_id, ship_token, "pdf")
        )

        upload_result = self._s3.upload_file(
            file_content=pdf_bytes,
            filename=s3_filename,
            folder=settings.BUCKET_POD_ATTACHMENTS_FOLDER,
            content_type="application/pdf",
        )
        object_key = upload_result.get("object_key")
        if not upload_result.get("success") or not object_key:
            raise RuntimeError(
                upload_result.get("error_message") or "S3 upload failed"
            )

        persist = insert_document(
            DocumentType.POD_ATTACHMENT,
            storage_key=str(object_key),
            shipments_row_id=shipments_row_id,
            attachment_id=attachment_id,
        )
        document_id = persist.get("id") if persist.get("stored") else None
        if not persist.get("stored"):
            logger.warning(
                "stage_pod_attachment: documents insert failed shipments_row_id=%s err=%s",
                shipments_row_id,
                persist.get("error"),
            )

        return PodAttachmentStageResult(
            object_key=str(object_key),
            document_id=str(document_id) if document_id else None,
            attachment_id=attachment_id,
        )
