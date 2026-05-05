"""Unit tests for ``app.tools.turvo`` — sync Turvo tools (plain inputs only).

Nodes resolve ``app_user_id`` from ``state`` (see ``workflows.nodes.turvo``);
these tests cover the tool layer: stubs when unconfigured or missing user,
mocked integration calls, and error containment.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from app.integrations.turvo.public_api_client import TurvoApiError
from app.tools import turvo as turvo_tool


def _patch_settings(
    monkeypatch: pytest.MonkeyPatch,
    *,
    publicapi_url: str | None = "https://my-sandbox-publicapi.turvo.com",
) -> None:
    monkeypatch.setattr(turvo_tool.settings, "TURVO_PUBLICAPI_URL", publicapi_url, raising=False)


def test_get_shipment_returns_stub_when_no_shipment_id(monkeypatch):
    _patch_settings(monkeypatch)
    out = turvo_tool.get_shipment(shipment_id=None, app_user_id="deb-test")
    assert out == {"shipment_id": "", "convoy": False}


def test_get_shipment_returns_stub_when_turvo_not_configured(monkeypatch):
    _patch_settings(monkeypatch, publicapi_url=None)

    with patch.object(turvo_tool, "get_shipment_async") as mock_async:
        out = turvo_tool.get_shipment(shipment_id="1000304706", app_user_id="deb-test")

    assert out == {"shipment_id": "1000304706", "convoy": False}
    mock_async.assert_not_called()


def test_get_shipment_returns_stub_when_app_user_id_missing(monkeypatch):
    _patch_settings(monkeypatch)

    with patch.object(turvo_tool, "get_shipment_async") as mock_async:
        out = turvo_tool.get_shipment(shipment_id="1000304706", app_user_id=None)

    assert out == {"shipment_id": "1000304706", "convoy": False}
    mock_async.assert_not_called()


def test_get_shipment_uses_explicit_app_user_id(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_async(app_user_id: str, shipment_id: Any) -> dict[str, Any]:
        assert app_user_id == "state-user"
        assert str(shipment_id) == "1000304706"
        return {"id": 1000304706, "convoy": False}

    with patch.object(turvo_tool, "get_shipment_async", side_effect=fake_async):
        out = turvo_tool.get_shipment(
            shipment_id="1000304706",
            app_user_id="state-user",
        )

    assert out == {"id": 1000304706, "convoy": False}


def test_get_shipment_calls_api_with_env_default_user(monkeypatch):
    """Caller (node) passes resolved user — tool does not read state or settings for identity."""
    _patch_settings(monkeypatch)

    async def fake_async(app_user_id: str, shipment_id: Any) -> dict[str, Any]:
        assert app_user_id == "env-user"
        return {"id": int(shipment_id), "convoy": True}

    with patch.object(turvo_tool, "get_shipment_async", side_effect=fake_async):
        out = turvo_tool.get_shipment(shipment_id="1000304706", app_user_id="env-user")

    assert out == {"id": 1000304706, "convoy": True}


def test_get_shipment_returns_stub_with_error_on_api_failure(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_async(app_user_id: str, shipment_id: Any) -> dict[str, Any]:
        raise TurvoApiError("nope", status_code=500, body="boom")

    with patch.object(turvo_tool, "get_shipment_async", side_effect=fake_async):
        out = turvo_tool.get_shipment(shipment_id="1000304706", app_user_id="env-user")

    assert out["shipment_id"] == "1000304706"
    assert out["convoy"] is False
    assert "error" in out


def test_get_shipment_returns_stub_with_error_on_unexpected_exception(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_async(app_user_id: str, shipment_id: Any) -> dict[str, Any]:
        raise RuntimeError("kaboom")

    with patch.object(turvo_tool, "get_shipment_async", side_effect=fake_async):
        out = turvo_tool.get_shipment(shipment_id="1000304706", app_user_id="env-user")

    assert out["shipment_id"] == "1000304706"
    assert out["convoy"] is False
    assert out["error"] == "unexpected_error"


def test_check_pod_by_shipment_id_requires_shipment_id(monkeypatch):
    _patch_settings(monkeypatch)
    out = turvo_tool.check_pod_by_shipment_id(shipment_id=None, app_user_id="deb-test")
    assert out["success"] is False
    assert out["shipment_id"] == ""


def test_check_pod_by_shipment_id_skips_when_not_configured(monkeypatch):
    _patch_settings(monkeypatch, publicapi_url=None)

    with patch.object(turvo_tool, "check_pod_by_shipment_id_async") as mock_async:
        out = turvo_tool.check_pod_by_shipment_id(
            shipment_id="1000304706",
            app_user_id="deb-test",
        )

    assert out["success"] is False
    assert "not configured" in out["message"].lower()
    mock_async.assert_not_called()


def test_check_pod_by_shipment_id_uses_async_integration(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_check(app_user_id: str, shipment_id: Any) -> dict[str, Any]:
        assert app_user_id == "env-user"
        assert str(shipment_id) == "1000304706"
        return {
            "success": True,
            "shipment_id": str(shipment_id),
            "pod_exists": True,
            "pod_documents": [{"Basic": {}}],
            "all_documents_count": 3,
            "message": "POD found (1 document(s))",
        }

    with patch.object(
        turvo_tool, "check_pod_by_shipment_id_async", side_effect=fake_check
    ):
        out = turvo_tool.check_pod_by_shipment_id(
            shipment_id="1000304706",
            app_user_id="env-user",
        )

    assert out["success"] is True
    assert out["pod_exists"] is True
    assert out["all_documents_count"] == 3


def test_check_pod_by_shipment_id_maps_api_error(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_check(app_user_id: str, shipment_id: Any) -> dict[str, Any]:
        raise TurvoApiError("nope", status_code=500, body="boom")

    with patch.object(
        turvo_tool, "check_pod_by_shipment_id_async", side_effect=fake_check
    ):
        out = turvo_tool.check_pod_by_shipment_id(
            shipment_id="1000304706",
            app_user_id="env-user",
        )

    assert out["success"] is False
    assert out["pod_exists"] is False
    assert "Failed to check POD" in out["message"]
