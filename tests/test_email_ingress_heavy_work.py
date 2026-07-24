"""Edge Heavy-Work Gate: metadata-only heavy attachment classification."""

from __future__ import annotations

from app.domain.email_ingress_heavy_work import payload_requires_heavy_ingress_work


def _xlsx_attachment(name: str) -> dict:
    return {
        "id": "att-1",
        "name": name,
        "extension": "xlsx",
        "mime": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }


def test_no_attachments_is_not_heavy() -> None:
    assert payload_requires_heavy_ingress_work({"has_attachments": False}) is False
    assert payload_requires_heavy_ingress_work({}) is False


def test_delivery_locations_attachment_is_heavy() -> None:
    payload = {
        "has_attachments": True,
        "attachments": [_xlsx_attachment("delivery_location.xlsx")],
    }
    assert payload_requires_heavy_ingress_work(payload) is True


def test_load_tendering_attachment_is_heavy() -> None:
    payload = {
        "has_attachments": True,
        "attachments": [_xlsx_attachment("customers_orders_loads.xlsx")],
    }
    assert payload_requires_heavy_ingress_work(payload) is True


def test_unrelated_xlsx_is_not_heavy() -> None:
    payload = {
        "has_attachments": True,
        "attachments": [_xlsx_attachment("random_report.xlsx")],
    }
    assert payload_requires_heavy_ingress_work(payload) is False


def test_non_xlsx_attachment_is_not_heavy() -> None:
    payload = {
        "has_attachments": True,
        "attachments": [
            {
                "id": "att-1",
                "name": "signed_pod.pdf",
                "extension": "pdf",
                "mime": "application/pdf",
            }
        ],
    }
    assert payload_requires_heavy_ingress_work(payload) is False
