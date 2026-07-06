"""Revoke delayed reminder Celery tasks tracked on lifecycle metadata."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.celery_app import celery_app
from app.core.logger import get_logger
from app.core.service_db import run_with_repos
from app.domain.pending_reminder_tasks import (
    clear_pending_reminder_tasks,
    filter_pending_reminder_tasks,
    merge_pending_reminder_tasks,
    pending_reminder_tasks_from_metadata,
)

logger = get_logger(__name__)


class WorkflowReminderCancelService:
    """Register and revoke ETA reminder tasks stored on ``workflow_lifecycles.metadata``."""

    def register_tasks(
        self,
        *,
        lifecycle_id: str,
        entries: list[dict[str, Any]],
    ) -> None:
        """Append Celery task ids after successful ``apply_async`` enqueue."""
        lid = str(lifecycle_id or "").strip()
        if not lid or not entries:
            return
        normalized: list[dict[str, Any]] = []
        for entry in entries:
            task_id = str(entry.get("task_id") or "").strip()
            if not task_id:
                continue
            row: dict[str, Any] = {"task_id": task_id}
            event_type = str(entry.get("event_type") or "").strip()
            if event_type:
                row["event_type"] = event_type
            step = entry.get("step")
            if step is not None:
                try:
                    row["step"] = int(step)
                except (TypeError, ValueError):
                    pass
            normalized.append(row)
        if not normalized:
            return

        def _persist(repos: Any) -> None:
            row = repos.workflow_lifecycles.read_row_by_id(lid) or {}
            patch = merge_pending_reminder_tasks(
                row.get("metadata"),
                new_entries=normalized,
            )
            repos.workflow_lifecycles.patch_metadata(
                lifecycle_id=lid,
                metadata_patch=patch,
            )

        try:
            run_with_repos(_persist)
        except Exception:
            logger.exception(
                "workflow_reminder_cancel register failed lifecycle_id=%s",
                lid,
            )

    def cancel_all(self, *, lifecycle_id: str) -> int:
        """Revoke every pending reminder task for a lifecycle."""
        return self._cancel_matching(
            lifecycle_id=lifecycle_id,
            match=lambda _item: True,
            clear_all=True,
        )

    def _cancel_matching(
        self,
        *,
        lifecycle_id: str,
        match: Callable[[dict[str, Any]], bool],
        clear_all: bool = False,
    ) -> int:
        lid = str(lifecycle_id or "").strip()
        if not lid:
            return 0

        def _load(repos: Any) -> tuple[list[dict[str, Any]], list[str]]:
            row = repos.workflow_lifecycles.read_row_by_id(lid) or {}
            pending = pending_reminder_tasks_from_metadata(row.get("metadata"))
            revoke_ids: list[str] = []
            for item in pending:
                if not match(item):
                    continue
                task_id = str(item.get("task_id") or "").strip()
                if task_id:
                    revoke_ids.append(task_id)
            return pending, revoke_ids

        try:
            _pending, revoke_ids = run_with_repos(_load)
        except Exception:
            logger.exception(
                "workflow_reminder_cancel load failed lifecycle_id=%s",
                lid,
            )
            return 0

        if not revoke_ids:
            return 0

        revoked = 0
        for task_id in revoke_ids:
            try:
                celery_app.control.revoke(task_id, terminate=False)
                revoked += 1
            except Exception:
                logger.exception(
                    "workflow_reminder_cancel revoke failed task_id=%s lifecycle_id=%s",
                    task_id,
                    lid,
                )

        remove_ids = frozenset(revoke_ids)

        def _persist(repos: Any) -> None:
            if clear_all and len(revoke_ids) > 0:
                patch = clear_pending_reminder_tasks()
            else:
                row = repos.workflow_lifecycles.read_row_by_id(lid) or {}
                patch = filter_pending_reminder_tasks(
                    row.get("metadata"),
                    remove_task_ids=remove_ids,
                )
            repos.workflow_lifecycles.patch_metadata(
                lifecycle_id=lid,
                metadata_patch=patch,
            )

        try:
            run_with_repos(_persist)
        except Exception:
            logger.exception(
                "workflow_reminder_cancel metadata update failed lifecycle_id=%s",
                lid,
            )

        logger.info(
            "workflow_reminder_cancel revoked=%s lifecycle_id=%s",
            revoked,
            lid,
        )
        return revoked
