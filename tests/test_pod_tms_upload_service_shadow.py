"""Tests for PodTmsUploadService workflow shadow mode."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from app.services.pod_tms_upload_service import PodTmsUploadService


def test_upload_merged_pod_shadow_skips_tool() -> None:
    state = SimpleNamespace(
        data={
            "shipment_id": "ship-1",
            "tenant_slug": "t3ra",
            "workflow_shadow_mode": True,
            "tenant_settings": {"pod_lifecycle": {"shadow_mode": True}},
        }
    )
    svc = PodTmsUploadService()
    with patch("app.tools.turvo.upload_to_turvo") as upload_mock:
        result = svc.upload_merged_pod_from_state(state)
    upload_mock.assert_not_called()
    assert result["success"] is True
    assert result["shadow_skipped"] is True
