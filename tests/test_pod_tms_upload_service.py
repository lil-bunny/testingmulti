"""Unit tests for PodTmsUploadService."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.pod_tms_upload_service import (
    PodLifecycleNotFoundError,
    PodTmsUploadService,
)
from app.services.shipments_service import ShipmentsService

_MIN_PDF = b"%PDF-1.4\n1 0 obj\n"
_SHIPMENTS_ROW_UUID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def test_validate_pdf_rejects_non_pdf():
    with pytest.raises(ValueError, match="not a valid PDF"):
        PodTmsUploadService.validate_pdf(b"not-a-pdf")


def test_stage_pod_attachment_success():
    svc = PodTmsUploadService(
        s3_bucket=MagicMock(
            upload_file=MagicMock(
                return_value={"success": True, "object_key": "pod_attachments/x.pdf"}
            )
        ),
    )
    out = svc.stage_pod_attachment(
        pdf_bytes=_MIN_PDF,
        shipment_id="1000324895",
        shipments_row_id="ship-uuid",
    )

    assert out.object_key == "pod_attachments/x.pdf"
    assert out.document_id is None
    assert out.attachment_id.startswith("manual-")


def test_resolve_pod_lifecycle_not_found_without_shipment():
    svc = PodTmsUploadService(
        shipments_service=MagicMock(get_by_id=MagicMock(return_value=None)),
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.pod_tms_upload_service.resolve_graph_tenant_to_uuid",
            lambda slug: "tenant-uuid",
        )
        with pytest.raises(PodLifecycleNotFoundError, match="shipment not found"):
            svc.resolve_pod_lifecycle(
                tenant_slug="t3ra",
                shipment_id=_SHIPMENTS_ROW_UUID,
            )


def test_resolve_pod_lifecycle_not_found_for_non_uuid():
    repo = MagicMock()
    svc = PodTmsUploadService(
        shipments_service=ShipmentsService(shipments_repository=repo),
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.pod_tms_upload_service.resolve_graph_tenant_to_uuid",
            lambda slug: "tenant-uuid",
        )
        with pytest.raises(PodLifecycleNotFoundError, match="shipment not found"):
            svc.resolve_pod_lifecycle(tenant_slug="t3ra", shipment_id="1000324895")
    repo.get_by_tenant_and_id_tx.assert_not_called()


def test_resolve_pod_lifecycle_not_found_without_lifecycle():
    svc = PodTmsUploadService(
        shipments_service=MagicMock(
            get_by_id=MagicMock(
                return_value={
                    "id": _SHIPMENTS_ROW_UUID,
                    "shipment_number": "1000324895",
                }
            )
        ),
        lifecycle_service=MagicMock(
            read_lifecycle=MagicMock(return_value={"found": False})
        ),
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            "app.services.pod_tms_upload_service.resolve_graph_tenant_to_uuid",
            lambda slug: "tenant-uuid",
        )
        with pytest.raises(PodLifecycleNotFoundError, match="pod_lifecycle not found"):
            svc.resolve_pod_lifecycle(
                tenant_slug="t3ra",
                shipment_id=_SHIPMENTS_ROW_UUID,
            )
