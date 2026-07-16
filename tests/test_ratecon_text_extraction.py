"""Unit tests for ratecon text-first extraction with vision fallback."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services import ratecon_extraction as mod


def test_extract_uses_text_path_when_critical_fields_present(tmp_path):
    pdf_path = tmp_path / "ratecon.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    prompts = MagicMock()
    prompts.system = "sys"
    prompts.user = "user"

    with (
        patch.object(mod, "resolve_ratecon_vision_prompts", return_value=(prompts, MagicMock())),
        patch.object(
            mod.PromptTraceMetadata,
            "from_load",
            return_value=None,
        ),
        patch.object(
            mod,
            "_extract_via_text",
            return_value=(
                [{"page_number": 1, "extraction_mode": "text"}],
                {
                    "shipment_identifiers": ["62670"],
                    "primary_identifier": "62670",
                    "po_number": "62670",
                    "carrier_name": "Test",
                    "pickup_location": None,
                    "pickup_address": None,
                    "delivery_location": None,
                    "delivery_address": None,
                    "pickup_date": None,
                    "delivery_date": None,
                    "broker_name": None,
                },
            ),
        ) as text_path,
        patch.object(mod, "_extract_via_vision") as vision_path,
    ):
        pages, data = mod.extract_from_pdf_path(str(pdf_path))

    assert pages[0]["extraction_mode"] == "text"
    assert data["primary_identifier"] == "62670"
    text_path.assert_called_once()
    vision_path.assert_not_called()


def test_extract_falls_back_to_vision_when_text_path_returns_none(tmp_path):
    pdf_path = tmp_path / "ratecon.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake")

    prompts = MagicMock()
    prompts.system = "sys"
    prompts.user = "user"

    with (
        patch.object(mod, "resolve_ratecon_vision_prompts", return_value=(prompts, MagicMock())),
        patch.object(mod.PromptTraceMetadata, "from_load", return_value=None),
        patch.object(mod, "_extract_via_text", return_value=None),
        patch.object(
            mod,
            "_extract_via_vision",
            return_value=(
                [{"page_number": 1, "extraction_mode": "vision"}],
                {"shipment_identifiers": ["1"], "primary_identifier": "1"},
            ),
        ) as vision_path,
    ):
        pages, data = mod.extract_from_pdf_path(str(pdf_path))

    assert pages[0]["extraction_mode"] == "vision"
    assert data["primary_identifier"] == "1"
    vision_path.assert_called_once()


def test_has_critical_fields():
    assert mod._has_critical_fields({"shipment_identifiers": ["62670"]})
    assert mod._has_critical_fields(
        {"carrier_name": "A", "pickup_location": "B", "shipment_identifiers": []}
    )
    assert not mod._has_critical_fields(_empty := mod._empty_extracted())
