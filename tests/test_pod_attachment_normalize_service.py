"""Tests for graph-path ``PodAttachmentNormalizeService``."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.services.pod_lifecycle.attachment_normalize_service import (
    PodAttachmentNormalizeService,
)


def test_normalize_from_state_data_passes_prior_map():
    prior = {"att-1": {"is_valid_document": True, "confidence": 0.91}}
    normalizer = MagicMock()
    normalizer.normalize.return_value = {
        "success": True,
        "pod_merged_pdf_object_key": "pod_attachments/merged.pdf",
        "classification_results": [{"from_ingress_gate": True}],
    }

    svc = PodAttachmentNormalizeService(normalizer=normalizer)
    data = {
        "pod_object_keys": ["pod_attachments/pod_att-1_SHIP.pdf"],
        "shipment_id": "SHIP",
        "attachment_normalization": {
            "classification_by_attachment_id": prior,
        },
    }

    out = svc.normalize_from_state_data(data)

    normalizer.normalize.assert_called_once_with(
        ["pod_attachments/pod_att-1_SHIP.pdf"],
        shipment_number="SHIP",
        prior_classification_by_attachment_id=prior,
        upload_merged=True,
    )
    assert out["success"] is True


def test_normalize_from_state_data_without_prior_map():
    normalizer = MagicMock()
    normalizer.normalize.return_value = {"success": True}
    svc = PodAttachmentNormalizeService(normalizer=normalizer)

    svc.normalize_from_state_data(
        {"pod_object_keys": ["pod_attachments/pod_x.pdf"], "shipment_id": "S1"}
    )

    normalizer.normalize.assert_called_once_with(
        ["pod_attachments/pod_x.pdf"],
        shipment_number="S1",
        prior_classification_by_attachment_id=None,
        upload_merged=True,
    )
