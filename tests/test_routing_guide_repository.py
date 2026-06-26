"""Unit tests for ``RoutingGuideRepository`` row mapping."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

from app.domain.routing_guide.types import PlanCarrierSlot
from app.repositories.routing_guide_repository import RoutingGuideRepository


def test_list_by_tenant_zipcode_maps_city_state_aliases_and_carriers() -> None:
    session = MagicMock()
    session.execute.return_value.all.return_value = [
        (
            "guide-1",
            "Pharmavite",
            "43031",
            "New Albany",
            "OH",
            json.dumps({"source": "seed"}),
            json.dumps(["PHARMAVITE"]),
            json.dumps(
                {"a": {"name": "Fitzmark", "email": "fitz@example.com"}}
            ),
        )
    ]
    repo = RoutingGuideRepository(session)

    rows = repo.list_by_tenant_zipcode(tenant_id="tenant-1", zipcode="43031")

    assert len(rows) == 1
    row = rows[0]
    assert row.city == "New Albany"
    assert row.state == "OH"
    assert row.metadata == {"source": "seed"}
    assert row.customer_aliases == ["PHARMAVITE"]
    assert row.carriers == {
        "a": PlanCarrierSlot(name="Fitzmark", email="fitz@example.com"),
    }
