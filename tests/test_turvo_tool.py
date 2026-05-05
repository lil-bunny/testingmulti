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
from app.integrations.turvo.load_to_shipment import shipment_id_from_list_response
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


def test_load_id_to_shipment_id_requires_load_id(monkeypatch):
    _patch_settings(monkeypatch)
    out = turvo_tool.load_id_to_shipment_id(load_id=None, app_user_id="deb-test")
    assert out["success"] is False
    assert out["load_id"] == ""
    assert out["shipment_id"] is None


def test_load_id_to_shipment_id_skips_when_not_configured(monkeypatch):
    _patch_settings(monkeypatch, publicapi_url=None)

    with patch.object(turvo_tool, "load_id_to_shipment_id_async") as mock_async:
        out = turvo_tool.load_id_to_shipment_id(
            load_id="12345",
            app_user_id="deb-test",
        )

    assert out["success"] is False
    assert "not configured" in out["message"].lower()
    mock_async.assert_not_called()


def test_load_id_to_shipment_id_skips_when_no_app_user(monkeypatch):
    _patch_settings(monkeypatch)
    monkeypatch.setattr(turvo_tool.settings, "TURVO_DEFAULT_APP_USER_ID", None, raising=False)

    with patch.object(turvo_tool, "load_id_to_shipment_id_async") as mock_async:
        out = turvo_tool.load_id_to_shipment_id(load_id="12345", app_user_id=None)

    assert out["success"] is False
    assert "app_user_id" in out["message"].lower() or "not configured" in out["message"].lower()
    mock_async.assert_not_called()


def test_load_id_to_shipment_id_uses_env_default_user(monkeypatch):
    _patch_settings(monkeypatch)
    monkeypatch.setattr(turvo_tool.settings, "TURVO_DEFAULT_APP_USER_ID", "default-user", raising=False)

    async def fake_async(app_user_id: str, load_id: str) -> str:
        assert app_user_id == "default-user"
        assert load_id == "12345"
        return "999"

    with patch.object(turvo_tool, "load_id_to_shipment_id_async", side_effect=fake_async):
        out = turvo_tool.load_id_to_shipment_id(load_id="12345", app_user_id=None)

    assert out["success"] is True
    assert out["shipment_id"] == "999"
    assert out["load_id"] == "12345"


def test_load_id_to_shipment_id_success(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_async(app_user_id: str, load_id: str) -> str:
        return "SHIP-1"

    with patch.object(turvo_tool, "load_id_to_shipment_id_async", side_effect=fake_async):
        out = turvo_tool.load_id_to_shipment_id(load_id="12345", app_user_id="deb-test")

    assert out["success"] is True
    assert out["shipment_id"] == "SHIP-1"


def test_load_id_to_shipment_id_not_found(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_async(app_user_id: str, load_id: str) -> None:
        return None

    with patch.object(turvo_tool, "load_id_to_shipment_id_async", side_effect=fake_async):
        out = turvo_tool.load_id_to_shipment_id(load_id="12345", app_user_id="deb-test")

    assert out["success"] is False
    assert out["shipment_id"] is None
    assert "could not extract" in out["message"].lower() or "no shipment" in out["message"].lower()


def test_load_id_to_shipment_id_maps_api_error(monkeypatch):
    _patch_settings(monkeypatch)

    async def fake_async(app_user_id: str, load_id: str) -> str:
        raise TurvoApiError("nope", status_code=500, body="boom")

    with patch.object(turvo_tool, "load_id_to_shipment_id_async", side_effect=fake_async):
        out = turvo_tool.load_id_to_shipment_id(load_id="12345", app_user_id="env-user")

    assert out["success"] is False
    assert out["shipment_id"] is None
    assert "Failed to resolve" in out["message"]


def test_shipment_id_from_list_response_matches_turvo_sample():
    body = {
        "Status": "SUCCESS",
        "details": {
            "pagination": {},
            "shipments": [
                {
                    "id": 1000315335,
                    "customId": "30381",
                }
            ],
        },
    }
    assert shipment_id_from_list_response(body, "30381") == "1000315335"


def test_shipment_id_from_list_response_custom_mismatch_with_multiple_rows():
    body = {
        "details": {
            "shipments": [
                {"id": 1, "customId": "other"},
                {"id": 2, "customId": "30381"},
            ]
        }
    }
    assert shipment_id_from_list_response(body, "30381") == "2"


def test_shipment_id_from_list_response_empty():
    assert shipment_id_from_list_response({"details": {"shipments": []}}, "30381") is None
