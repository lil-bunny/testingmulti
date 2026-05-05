"""Unit tests for ``ratecon_shipment_in_workflow_correlation`` and ``read_correlation_by_shipment_id`` wrappers."""

from __future__ import annotations

from unittest.mock import patch

from app.tools import workflow_correlation as wc


def test_ratecon_prefers_shipment_id_skips_turvo():
    with patch.object(wc, "load_id_to_shipment_id") as mock_turvo:
        with patch.object(wc, "read_correlation_by_shipment_id") as mock_read:
            mock_read.return_value = {
                "found": True,
                "payload": {"shipment_id": "S1", "workflow_instance_id": "w1"},
            }
            out = wc.ratecon_shipment_in_workflow_correlation(
                "L99",
                shipment_id="S1",
                app_user_id="user",
            )
    mock_turvo.assert_not_called()
    mock_read.assert_called_once_with("S1")
    assert out["in_workflow_correlation"] is True
    assert out["shipment_id"] == "S1"
    assert out["load_id"] == "L99"


def test_ratecon_load_id_only_calls_turvo_then_read():
    with patch.object(wc, "load_id_to_shipment_id") as mock_turvo:
        with patch.object(wc, "read_correlation_by_shipment_id") as mock_read:
            mock_turvo.return_value = {
                "success": True,
                "load_id": "56368",
                "shipment_id": "SHIP-1",
                "message": "ok",
            }
            mock_read.return_value = {"found": False, "payload": {}}
            out = wc.ratecon_shipment_in_workflow_correlation(
                "56368",
                app_user_id="u1",
            )
    mock_turvo.assert_called_once_with("56368", app_user_id="u1")
    mock_read.assert_called_once_with("SHIP-1")
    assert out["in_workflow_correlation"] is False
    assert out["shipment_id"] == "SHIP-1"
    assert out["load_id"] == "56368"


def test_ratecon_turvo_failure():
    with patch.object(wc, "load_id_to_shipment_id") as mock_turvo:
        with patch.object(wc, "read_correlation_by_shipment_id") as mock_read:
            mock_turvo.return_value = {
                "success": False,
                "load_id": "1",
                "shipment_id": None,
                "message": "nope",
            }
            out = wc.ratecon_shipment_in_workflow_correlation("1")
    mock_read.assert_not_called()
    assert out["in_workflow_correlation"] is False
    assert out["shipment_id"] is None
    assert out["message"] == "nope"


def test_ratecon_missing_both_ids():
    out = wc.ratecon_shipment_in_workflow_correlation(None, shipment_id=None)
    assert out["in_workflow_correlation"] is False
    assert out["shipment_id"] is None
    assert "missing" in out["message"].lower()


def test_read_correlation_by_shipment_id_empty():
    assert wc.read_correlation_by_shipment_id("") == {"found": False, "payload": {}}
    assert wc.read_correlation_by_shipment_id("   ") == {"found": False, "payload": {}}


def test_persist_thread_missing_ids():
    assert wc.persist_correlation_thread_for_shipment("", "L1", "t1") == {
        "stored": False,
        "error": "missing_shipment_id_or_email_thread_id",
    }
    assert wc.persist_correlation_thread_for_shipment("S1", "L1", "") == {
        "stored": False,
        "error": "missing_shipment_id_or_email_thread_id",
    }


def test_persist_thread_no_row_requires_workflow_instance_id():
    with patch.object(wc, "read_correlation_by_shipment_id", return_value={"found": False, "payload": {}}):
        assert wc.persist_correlation_thread_for_shipment("S1", "L1", "thr") == {
            "stored": False,
            "error": "missing_workflow_instance_id_new_row",
        }


def test_persist_thread_inserts_when_no_row_with_workflow_instance_id():
    with patch.object(wc, "read_correlation_by_shipment_id", return_value={"found": False, "payload": {}}):
        with patch.object(wc, "upsert_by_key") as mock_upsert:
            mock_upsert.return_value = {"key": "S1", "payload": {}}
            out = wc.persist_correlation_thread_for_shipment(
                "S1",
                "L1",
                "thr",
                workflow_instance_id="run-9",
                workflow_name="ratecon",
            )
    mock_upsert.assert_called_once_with(
        "S1",
        {
            "workflow_name": "ratecon",
            "workflow_instance_id": "run-9",
            "shipment_id": "S1",
            "load_id": "L1",
            "email_thread_id": "thr",
        },
    )
    assert out["stored"] is True
    assert out["workflow_correlation"] == {"key": "S1", "payload": {}}


def test_persist_thread_missing_workflow_instance_id():
    with patch.object(
        wc,
        "read_correlation_by_shipment_id",
        return_value={"found": True, "payload": {"shipment_id": "S1"}},
    ):
        assert wc.persist_correlation_thread_for_shipment("S1", "L1", "thr") == {
            "stored": False,
            "error": "missing_workflow_instance_id",
        }


def test_persist_thread_calls_upsert_with_merged_payload():
    read_payload = {
        "workflow_name": "pod_lifecycle",
        "workflow_instance_id": "wi-1",
        "shipment_id": "S1",
        "load_id": "old_load",
        "email_thread_id": "",
    }
    with patch.object(
        wc,
        "read_correlation_by_shipment_id",
        return_value={"found": True, "payload": dict(read_payload)},
    ) as mock_read:
        with patch.object(wc, "upsert_by_key") as mock_upsert:
            mock_upsert.return_value = {"key": "S1", "payload": {}}
            out = wc.persist_correlation_thread_for_shipment("S1", "L99", "thread-a")
    mock_read.assert_called_once_with("S1")
    mock_upsert.assert_called_once_with(
        "S1",
        {
            "workflow_name": "pod_lifecycle",
            "workflow_instance_id": "wi-1",
            "shipment_id": "S1",
            "load_id": "L99",
            "email_thread_id": "thread-a",
        },
    )
    assert out["stored"] is True
    assert out["workflow_correlation"] == {"key": "S1", "payload": {}}


def test_persist_thread_keeps_existing_load_when_new_empty():
    with patch.object(
        wc,
        "read_correlation_by_shipment_id",
        return_value={
            "found": True,
            "payload": {
                "workflow_name": "pod_lifecycle",
                "workflow_instance_id": "wi-1",
                "shipment_id": "S1",
                "load_id": "keep-me",
            },
        },
    ):
        with patch.object(wc, "upsert_by_key") as mock_upsert:
            mock_upsert.return_value = {"key": "S1", "payload": {}}
            wc.persist_correlation_thread_for_shipment("S1", "", "thr")
    args = mock_upsert.call_args[0]
    assert args[1]["load_id"] == "keep-me"
