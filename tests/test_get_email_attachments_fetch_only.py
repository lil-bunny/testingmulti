from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.state import WorkflowState


@patch("app.workflows.nodes.email.get_email_attachments_tool")
def test_get_email_attachments_fetches_bytes_without_s3_upload(
    mock_fetch: MagicMock,
) -> None:
    from app.workflows.nodes.email import get_email_attachments

    mock_fetch.return_value = b"%PDF-1.4 test pod"
    state = WorkflowState(
        tenant_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
        tenant_slug="t3ra",
        execution_id="run-1",
        data={
            "email_id": "email-1",
            "account_id": "acct-1",
            "shipment_id": "SHIP-1",
            "attachments": [{"id": "att-1", "name": "pod.pdf"}],
        },
    )

    with patch(
        "app.workflows.nodes.email.PodLifecycleEmailService"
    ) as mock_email_svc:
        mock_email_svc.return_value.resolve_sender_account_id.return_value = "acct-1"
        get_email_attachments(state)

    assert state.data["attachment_bytes_by_id"] == {"att-1": b"%PDF-1.4 test pod"}
    assert state.data["pod_object_keys"] == []
    assert state.data["get_email_attachments_results"][0]["success"] is True
    assert state.data["get_email_attachments_results"][0]["object_key"] is None
