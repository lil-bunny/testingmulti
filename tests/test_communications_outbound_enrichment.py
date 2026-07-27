"""Outbound tender send: enrich external_id to Unipile deprecated_id for reply chains."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.communications.service import CommunicationsService


TENANT_ID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
TRACKING_ID = "8KsQwPb_SaygD_W3Wj3azQ"
DEPRECATED_ID = "DWAjX8BsWQiL2lcBmw3PVg"
SENT_THREAD = (
    "AAQkADc3ZDhmN2U0LWIzNDctNDQ5OS1iNmYzLTQ0YWMwNWI1MzZiZAAQADfY0J5_UQhKo0p5ordMf1Q="
)
SENT_FOLDER = (
    "AAMkADc3ZDhmN2U0LWIzNDctNDQ5OS1iNmYzLTQ0YWMwNWI1MzZiZAAuAAAAAAAbbsEegzRRToAlQuYikGVn"
    "AQCqsUzoh3e4QajuQc55Jjn6AAAAAAEJAAA="
)


@patch("app.services.communications.service.Unipile")
def test_record_outbound_uses_deprecated_id_from_sent_folder(
    mock_unipile_cls: MagicMock,
) -> None:
    repo = MagicMock()
    repo.insert.return_value = "comm-1"
    svc = CommunicationsService(repository=repo)

    unipile = MagicMock()
    mock_unipile_cls.return_value = unipile
    unipile.list_emails.return_value = {
        "items": [
            {
                "id": "RAuCjQRHXn-gjzcpaTRjIg",
                "deprecated_id": DEPRECATED_ID,
                "tracking_id": TRACKING_ID,
                "thread_id": SENT_THREAD,
            }
        ]
    }

    comm_id = svc.record_outbound_from_send(
        TENANT_ID,
        send_result={"success": True, "tracking_id": TRACKING_ID, "message_id": TRACKING_ID},
        body="<p>tender</p>",
        subject="PICK UP REQUEST # 95118",
        to=["ayverse@outlook.com"],
        account_id="acct-1",
        workflow_run_id="11111111-1111-1111-1111-111111111111",
        sent_folder_id=SENT_FOLDER,
    )

    assert comm_id == "comm-1"
    unipile.list_emails.assert_called_once_with(
        account_id="acct-1",
        folder=SENT_FOLDER,
        limit=50,
        meta_only=True,
        to="ayverse@outlook.com",
    )
    row = repo.insert.call_args[0][0]
    assert row["external_id"] == DEPRECATED_ID
    assert row["thread_id"] == SENT_THREAD


@patch("app.services.communications.service.Unipile")
def test_record_outbound_falls_back_to_tracking_id_when_enrichment_misses(
    mock_unipile_cls: MagicMock,
) -> None:
    repo = MagicMock()
    repo.insert.return_value = "comm-2"
    svc = CommunicationsService(repository=repo)

    unipile = MagicMock()
    mock_unipile_cls.return_value = unipile
    unipile.list_emails.return_value = {"items": []}

    comm_id = svc.record_outbound_from_send(
        TENANT_ID,
        send_result={"success": True, "tracking_id": TRACKING_ID, "message_id": TRACKING_ID},
        body="<p>tender</p>",
        subject="PICK UP REQUEST # 95118",
        to=["ayverse@outlook.com"],
        account_id="acct-1",
        sent_folder_id=SENT_FOLDER,
    )

    assert comm_id == "comm-2"
    row = repo.insert.call_args[0][0]
    assert row["external_id"] == TRACKING_ID


def test_record_outbound_without_sent_folder_keeps_tracking_id() -> None:
    repo = MagicMock()
    repo.insert.return_value = "comm-3"
    svc = CommunicationsService(repository=repo)

    with patch("app.services.communications.service.Unipile") as mock_unipile_cls:
        comm_id = svc.record_outbound_from_send(
            TENANT_ID,
            send_result={
                "success": True,
                "tracking_id": TRACKING_ID,
                "message_id": TRACKING_ID,
            },
            body="<p>tender</p>",
            subject="PICK UP REQUEST # 95118",
            to=["ayverse@outlook.com"],
            account_id="acct-1",
        )

    assert comm_id == "comm-3"
    mock_unipile_cls.assert_not_called()
    row = repo.insert.call_args[0][0]
    assert row["external_id"] == TRACKING_ID
