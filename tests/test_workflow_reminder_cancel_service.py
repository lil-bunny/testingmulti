"""Tests for WorkflowReminderCancelService."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domain.pending_reminder_tasks import PENDING_REMINDER_TASKS_KEY
from app.services.workflow_reminder_cancel_service import WorkflowReminderCancelService


def _mock_repos(*, metadata: dict | None = None) -> MagicMock:
    repos = MagicMock()
    repos.workflow_lifecycles.read_row_by_id.return_value = {
        "id": "wl-1",
        "metadata": metadata or {},
    }
    return repos


@patch("app.services.workflow_reminder_cancel_service.run_with_repos")
def test_register_tasks_appends_to_metadata(mock_run: MagicMock) -> None:
    repos = _mock_repos(
        metadata={PENDING_REMINDER_TASKS_KEY: [{"task_id": "existing"}]}
    )
    mock_run.side_effect = lambda fn: fn(repos)

    WorkflowReminderCancelService().register_tasks(
        lifecycle_id="wl-1",
        entries=[{"task_id": "t-new", "event_type": "reminder_due", "step": 2}],
    )

    repos.workflow_lifecycles.patch_metadata.assert_called_once()
    patch = repos.workflow_lifecycles.patch_metadata.call_args.kwargs["metadata_patch"]
    assert patch[PENDING_REMINDER_TASKS_KEY] == [
        {"task_id": "existing"},
        {"task_id": "t-new", "event_type": "reminder_due", "step": 2},
    ]


@patch("app.services.workflow_reminder_cancel_service.run_with_repos")
def test_register_tasks_noop_on_empty(mock_run: MagicMock) -> None:
    WorkflowReminderCancelService().register_tasks(lifecycle_id="wl-1", entries=[])
    mock_run.assert_not_called()


@patch("app.services.workflow_reminder_cancel_service.celery_app")
@patch("app.services.workflow_reminder_cancel_service.run_with_repos")
def test_cancel_all_revokes_and_clears(mock_run: MagicMock, mock_celery: MagicMock) -> None:
    repos = _mock_repos(
        metadata={
            PENDING_REMINDER_TASKS_KEY: [
                {"task_id": "t1"},
                {"task_id": "t2"},
            ]
        }
    )
    mock_run.side_effect = lambda fn: fn(repos)

    revoked = WorkflowReminderCancelService().cancel_all(lifecycle_id="wl-1")

    assert revoked == 2
    assert mock_celery.control.revoke.call_count == 2
    patch = repos.workflow_lifecycles.patch_metadata.call_args.kwargs["metadata_patch"]
    assert patch == {PENDING_REMINDER_TASKS_KEY: []}


@patch("app.services.workflow_reminder_cancel_service.run_with_repos")
def test_cancel_all_no_tasks(mock_run: MagicMock) -> None:
    repos = _mock_repos(metadata={})
    mock_run.side_effect = lambda fn: fn(repos)

    revoked = WorkflowReminderCancelService().cancel_all(lifecycle_id="wl-1")

    assert revoked == 0
    repos.workflow_lifecycles.patch_metadata.assert_not_called()
