"""Tests for Celery POD attachment ingress gate."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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

    with patch(
        "app.services.pod_lifecycle.attachment_ingress_gate_service.fetch_email_attachment_bytes_with_retry",
        return_value=b"%PDF-1.4 pod",
    ):
        result = await gate.check(payload=payload)

    assert result == PodAttachmentIngressGateResult(
        eligible=True,
        normalization=normalization,
    )


@pytest.mark.asyncio
async def test_gate_skips_when_no_attachments():
    gate = PodAttachmentIngressGateService(normalizer=MagicMock())
    result = await gate.check(payload={"attachments": []})
    assert result.eligible is False
    assert result.skip_reason == "no_attachments"
