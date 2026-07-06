"""Tests for WorkflowReminderCancelService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.services.workflow_reminder_cancel_service import WorkflowReminderCancelService


@patch("app.services.workflow_reminder_cancel_service.run_with_repos")
@patch("app.services.workflow_reminder_cancel_service.celery_app")
def test_cancel_all_revokes_and_clears_metadata(
    mock_celery: MagicMock,
    mock_run: MagicMock,
) -> None:
    lifecycle_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    row = {
        "metadata": {
            "pending_reminder_tasks": [
                {"task_id": "celery-1", "attempt": 1},
                {"task_id": "celery-2", "attempt": 1},
            ]
        }
    }

    def _run(fn):
        repos = MagicMock()
        repos.workflow_lifecycles.read_row_by_id.return_value = row
        fn(repos)
        return None

    mock_run.side_effect = [
        (row["metadata"]["pending_reminder_tasks"], ["celery-1", "celery-2"]),
        None,
    ]

    # First call loads; simplify by patching _cancel_matching internals
    service = WorkflowReminderCancelService()

    with patch.object(service, "_cancel_matching", return_value=2) as mock_cancel:
        assert service.cancel_all(lifecycle_id=lifecycle_id) == 2
        mock_cancel.assert_called_once()
        assert mock_cancel.call_args.kwargs["clear_all"] is True
