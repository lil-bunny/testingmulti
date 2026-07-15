"""Read-only access to ``pack_codes`` for workflow nodes."""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from app.core.service_db import run_with_repos

if TYPE_CHECKING:
    from app.repositories.pack_codes_repository import PackCodesRepository


class PackCodeService:
    def __init__(self, repository: Optional[PackCodesRepository] = None) -> None:
        self._repository = repository

    def get_by_code(self, *, tenant_id: str, code: str) -> dict[str, Any] | None:
        if self._repository is not None:
            return self._repository.get_by_code(tenant_id=tenant_id, code=code)
        return run_with_repos(
            lambda repos: repos.pack_codes.get_by_code(tenant_id=tenant_id, code=code)
        )
