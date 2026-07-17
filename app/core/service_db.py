"""Helpers for services that open db_scope + db_transaction."""

from __future__ import annotations

from typing import TypeVar, TYPE_CHECKING

from app.core.db import db_scope, db_transaction

if TYPE_CHECKING:
    from app.core.db_repos import DbRepos
    from collections.abc import Callable

T = TypeVar("T")


def run_with_repos(fn: Callable[[DbRepos], T]) -> T:
    """Run ``fn(repos)`` inside one short-lived session and transaction."""
    with db_scope() as repos:
        with db_transaction(repos.session):
            return fn(repos)
