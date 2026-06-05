"""Read-only access to ``tenants`` (slug + settings) for workflow nodes."""

from __future__ import annotations

from typing import Any, Optional

from app.core.service_db import run_with_repos
from app.repositories.tenants_db_repository import TenantsDbRepository


class TenantsService:
    def __init__(self, repository: Optional[TenantsDbRepository] = None) -> None:
        self._repository = repository

    def get_by_slug(self, slug: str) -> dict[str, Any] | None:
        """
        Return tenant row keyed by ``slug`` (matches ``TENANT_CONFIGS`` keys), or None.

        ``settings`` is parsed JSON (empty dict if null).
        ``id`` is the UUID string used for ``tenders.tenant_id`` FK joins.
        """
        if self._repository is not None:
            return self._repository.get_by_slug(slug)
        return run_with_repos(lambda repos: repos.tenants.get_by_slug(slug))
