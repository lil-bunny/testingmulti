"""Service layer for workflow_runs table."""

from __future__ import annotations

import uuid


import psycopg

from app.core.config import settings
from app.core.logger import get_logger
from app.repositories.tenants_db_repository import resolve_graph_tenant_to_uuid
from typing import Any, Optional

from app.core.service_db import run_with_repos
from app.repositories.workflow_runs_repository import WorkflowRunsRepository


class WorkflowRunsService:
    def __init__(self, repository: Optional[WorkflowRunsRepository] = None) -> None:
        self._repository = repository

    def _repo(self, repos: Any) -> WorkflowRunsRepository:
        return self._repository or repos.workflow_runs

    @staticmethod
    def reminder_run_event_type(reminder_step: int | None) -> str | None:
        return WorkflowRunsRepository.reminder_run_event_type(reminder_step)

    def is_workflow_initial_path_blocked(
        self,
        *,
        tenant_id: str | None,
        event_type: str | None,
        workflow_lifecycle_id: str | None,
        shipment_id: str | None,
        exclude_run_id: str | None = None,
    ) -> bool:
        if self._repository is not None:
            return self._repository.is_workflow_initial_path_blocked(
                tenant_id=tenant_id,
                event_type=event_type,
                workflow_lifecycle_id=workflow_lifecycle_id,
                shipment_id=shipment_id,
                exclude_run_id=exclude_run_id,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).is_workflow_initial_path_blocked(
                tenant_id=tenant_id,
                event_type=event_type,
                workflow_lifecycle_id=workflow_lifecycle_id,
                shipment_id=shipment_id,
                exclude_run_id=exclude_run_id,
            )
        )

    def is_ratecon_completed_blocked_for_shipment(
        self,
        *,
        tenant_id: str | None,
        workflow_lifecycle_id: str | None,
        shipment_id: str | None,
        exclude_run_id: str | None = None,
    ) -> bool:
        if self._repository is not None:
            return self._repository.is_ratecon_completed_blocked_for_shipment(
                tenant_id=tenant_id,
                workflow_lifecycle_id=workflow_lifecycle_id,
                shipment_id=shipment_id,
                exclude_run_id=exclude_run_id,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).is_ratecon_completed_blocked_for_shipment(
                tenant_id=tenant_id,
                workflow_lifecycle_id=workflow_lifecycle_id,
                shipment_id=shipment_id,
                exclude_run_id=exclude_run_id,
            )
        )

    def record_workflow_run(
        self,
        *,
        run_id: str,
        tenant_id: str | None,
        event_type: str,
        workflow_lifecycle_id: str | None,
    ) -> bool:
        if self._repository is not None:
            return self._repository.record_workflow_run(
                run_id=run_id,
                tenant_id=tenant_id,
                event_type=event_type,
                workflow_lifecycle_id=workflow_lifecycle_id,
            )
        return run_with_repos(
            lambda repos: self._repo(repos).record_workflow_run(
                run_id=run_id,
                tenant_id=tenant_id,
                event_type=event_type,
                workflow_lifecycle_id=workflow_lifecycle_id,
            )
        )

    def fetch_workflow_run_by_id(self, *, run_id: str) -> dict[str, Any] | None:
        if self._repository is not None:
            return self._repository.fetch_workflow_run_by_id(run_id=run_id)
        return run_with_repos(
            lambda repos: self._repo(repos).fetch_workflow_run_by_id(run_id=run_id)
        )
