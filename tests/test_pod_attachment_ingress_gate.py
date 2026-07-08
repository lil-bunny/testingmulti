"""Tests for Celery POD attachment ingress gate."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.attachment_normalizer import in_memory_attachment_ref
from app.services.pod_lifecycle.attachment_ingress_gate_service import (
    PodAttachmentIngressGateResult,
    PodAttachmentIngressGateService,
)
from app.services.pod_lifecycle.ingress_service import POD_EMAIL_SKIP_INVALID_ATTACHMENT


@pytest.mark.asyncio
async def test_gate_skips_invalid_attachment():
    normalizer = MagicMock()
    normalizer.assess_attachments.return_value = {
        "success": False,
        "error": "No valid document attachments after classification",
        "classification_results": [],
        "rejected": [],
    }
    gate = PodAttachmentIngressGateService(normalizer=normalizer)

    payload = {
        "email_id": "email-1",
        "account_id": "acct-1",
        "shipment_id": "1001",
        "attachments": [{"id": "att-1", "name": "shot.png"}],
    }

    with patch(
        "app.services.pod_lifecycle.attachment_ingress_gate_service.fetch_email_attachment_bytes_with_retry",
        return_value=b"\x89PNG" + b"\x00" * 12000,
    ):
        result = await gate.check(payload=payload)

    assert result.eligible is False
    assert result.skip_reason == POD_EMAIL_SKIP_INVALID_ATTACHMENT
    normalizer.assess_attachments.assert_called_once()


@pytest.mark.asyncio
async def test_gate_passes_and_returns_normalization():
    normalization = {
        "success": True,
        "source_attachment_ids": ["att-1"],
        "classification_by_attachment_id": {
            "att-1": {"is_valid_document": True, "confidence": 0.9},
        },
        "classification_results": [],
        "rejected": [],
    }
    normalizer = MagicMock()
    normalizer.assess_attachments.return_value = normalization
    gate = PodAttachmentIngressGateService(normalizer=normalizer)

    payload = {
        "email_id": "email-2",
        "account_id": "acct-1",
        "shipment_id": "1002",
        "attachments": [{"id": "att-1", "name": "pod.pdf"}],
    }
    pdf_bytes = b"%PDF-1.4 pod"

    with patch(
        "app.services.pod_lifecycle.attachment_ingress_gate_service.fetch_email_attachment_bytes_with_retry",
        return_value=pdf_bytes,
    ):
        result = await gate.check(payload=payload)

    assert result == PodAttachmentIngressGateResult(
        eligible=True,
        normalization=normalization,
        valid_bytes_by_id={"att-1": pdf_bytes},
    )


@pytest.mark.asyncio
async def test_gate_returns_valid_bytes_only():
    ship = "1003"
    good_ref = in_memory_attachment_ref("att-valid", ship)
    bad_ref = in_memory_attachment_ref("att-bad", ship)
    normalization = {
        "success": True,
        "source_attachment_ids": ["att-valid"],
        "classification_by_attachment_id": {
            "att-valid": {"is_valid_document": True, "confidence": 0.9},
        },
        "classification_results": [],
        "rejected": [{"attachment_ref": bad_ref, "rejection_reason": "truck photo"}],
        "source_attachments_cleanup": {
            "valid_source": [{"attachment_ref": good_ref}],
            "rejected": [{"attachment_ref": bad_ref}],
        },
    }
    normalizer = MagicMock()
    normalizer.assess_attachments.return_value = normalization
    gate = PodAttachmentIngressGateService(normalizer=normalizer)

    payload = {
        "email_id": "email-3",
        "account_id": "acct-1",
        "shipment_id": ship,
        "attachments": [
            {"id": "att-valid", "name": "pod.pdf"},
            {"id": "att-bad", "name": "truck.png"},
        ],
    }

    with patch(
        "app.services.pod_lifecycle.attachment_ingress_gate_service.fetch_email_attachment_bytes_with_retry",
        side_effect=[b"%PDF-1.4 valid", b"\x89PNG" + b"\x00" * 12000],
    ):
        result = await gate.check(payload=payload)

    assert result.eligible is True
    assert result.valid_bytes_by_id == {"att-valid": b"%PDF-1.4 valid"}
    assert "att-bad" not in (result.valid_bytes_by_id or {})


@pytest.mark.asyncio
async def test_gate_skips_when_no_attachments():
    gate = PodAttachmentIngressGateService(normalizer=MagicMock())
    result = await gate.check(payload={"attachments": []})
    assert result.eligible is False
    assert result.skip_reason == "no_attachments"
