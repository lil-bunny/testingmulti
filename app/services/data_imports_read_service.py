"""Read ``data_imports`` rows and project spreadsheet cells to API-friendly dicts."""

from __future__ import annotations

from typing import Any, Mapping, Optional, Sequence

from app.core.service_db import run_with_repos
from app.domain.column_projection import drop_all_empty_projected_rows, project_row
from app.domain.data_import_tabular import iter_spreadsheet_rows
from app.repositories.data_imports_repository import DataImportsRepository


class DataImportsReadService:
    def __init__(self, repository: Optional[DataImportsRepository] = None) -> None:
        self._repository = repository

    def get_projected_rows(
        self,
        tenant_id: str,
        data_import_id: str,
        *,
        projection: Mapping[str, Sequence[str]],
    ) -> tuple[list[dict[str, Any]] | None, dict[str, Any]]:
        if self._repository is not None:
            raw = self._repository.fetch_raw_data_by_id(
                tenant_id=tenant_id, data_import_id=data_import_id
            )
        else:
            raw = run_with_repos(
                lambda repos: repos.data_imports.fetch_raw_data_by_id(
                    tenant_id=tenant_id, data_import_id=data_import_id
                )
            )

        if raw is None:
            return None, {}

        base_rows = list(iter_spreadsheet_rows(raw))
        if not base_rows:
            return [], {"source": "none", "reason": "no_spreadsheet"}

        projected = [project_row(r, projection) for r in base_rows]
        projected = drop_all_empty_projected_rows(projected)
        return projected, {"source": "spreadsheet"}
