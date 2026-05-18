"""Tests for ``app.services.ingest_service``."""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from decimal import Decimal
from io import BytesIO
from uuid import UUID

import pandas as pd
import pytest

from app.services import ingest_service
from app.services.ingest_service import DEFAULT_MAX_BINARY_BYTES


def test_ingest_none_and_dict_minimal() -> None:
    r = ingest_service.ingest_data("src", "t1", data=None)
    assert r["data"] == {}

    r2 = ingest_service.ingest_data("src", "t1", data={"a": 1})
    assert r2["data"]["a"] == 1


def test_ingest_data_type_echoed_when_provided() -> None:
    r = ingest_service.ingest_data("s", "t", data={}, data_type="  my_kind  ")
    assert r["data_type"] == "my_kind"


def test_ingest_data_type_optional_none() -> None:
    r = ingest_service.ingest_data("s", "t", data={})
    assert r.get("data_type") is None


def test_ingest_data_type_blank_raises() -> None:
    with pytest.raises(ValueError, match="data_type cannot be blank"):
        ingest_service.ingest_data("s", "t", data={}, data_type="   ")


def test_ingest_dict_sanitizes_types() -> None:
    uid = UUID("550e8400-e29b-41d4-a716-446655440000")
    d = ingest_service.ingest_data(
        "x",
        "t",
        data={
            "d": Decimal("12.340"),
            "u": uid,
            "when": datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
            "day": date(2026, 3, 4),
            "x": float("nan"),
            "y": frozenset(),
            "s": {3, 1, 2},
        },
    )["data"]
    assert d["d"] == "12.340"
    assert d["u"] == str(uid)
    assert "2026" in d["when"]
    assert d["day"] == "2026-03-04"
    assert d["x"] is None
    assert d["y"] == "frozenset()"
    assert isinstance(d["s"], list)
    assert set(d["s"]) == {1, 2, 3}
def test_ingest_str_json_object_and_wrapped_root() -> None:
    d = ingest_service.ingest_data("x", "t", data='{"k": "v"}')["data"]
    assert d == {"k": "v"}

    d2 = ingest_service.ingest_data("x", "t", data="[1, 2]")["data"]
    assert d2 == {"parsed": [1, 2]}

    d3 = ingest_service.ingest_data("x", "t", data="not json")["data"]
    assert d3 == {"raw_text": "not json"}


def test_ingest_bytes_envelope_and_oversize() -> None:
    body = b"hello"
    d = ingest_service.ingest_data(
        "x", "t", file_name="f.bin", data=body, max_binary_bytes=100
    )["data"]
    assert d["encoding"] == "base64"
    assert d["content"] == "aGVsbG8="

    big = b"x" * (DEFAULT_MAX_BINARY_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds max_binary_bytes"):
        ingest_service.ingest_data("x", "t", data=big)


def test_ingest_bytes_xlsx_parse_spreadsheet() -> None:
    buf = BytesIO()
    pd.DataFrame({"A": [1], "B": ["z"]}).to_excel(buf, index=False, engine="openpyxl")
    raw = buf.getvalue()
    d = ingest_service.ingest_data(
        "x",
        "t",
        file_name="orders.xlsx",
        data=raw,
        parse_spreadsheet=True,
    )["data"]
    assert d["encoding"] == "base64"
    assert "spreadsheet" in d
    assert d["spreadsheet"]["format"] == "xlsx"
    assert d["spreadsheet"]["sheets"][0]["rows"][0]["A"] == 1


def test_ingest_nested_bytes_rejects() -> None:
    with pytest.raises(ValueError, match="bytes values nested"):
        ingest_service.ingest_data(
            "x", "t", data={"nested": b"bad"}, allow_nested_binary=False
        )


def test_ingest_nested_bytes_allow() -> None:
    import base64

    d = ingest_service.ingest_data(
        "x",
        "t",
        data={"nested": b"ok"},
        allow_nested_binary=True,
    )["data"]
    assert d["nested"]["encoding"] == "base64"
    assert d["nested"]["content"] == base64.b64encode(b"ok").decode("ascii")


def test_result_round_trips_through_json_module() -> None:
    payload = ingest_service.ingest_data(
        "x",
        "t",
        data={"n": Decimal("9.001")},
    )
    dumped = json.dumps(payload["data"])
    assert isinstance(json.loads(dumped), dict)


def test_numpy_scalar_in_dict() -> None:
    try:
        import numpy as np
    except ImportError:
        pytest.skip("numpy bundled with pandas in this env")
    d = ingest_service.ingest_data("x", "t", data={"z": np.int64(42)})["data"]
    assert d["z"] == 42


def test_finalize_wraps_non_object_json_root() -> None:
    payload = ingest_service.ingest_data("x", "t", data="null")["data"]
    assert payload == {"parsed": None}
