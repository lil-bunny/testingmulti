"""Helpers for services that open db_scope + db_transaction."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from app.core.db import db_scope, db_transaction
from app.core.db_repos import DbRepos

T = TypeVar("T")


def run_with_repos(fn: Callable[[DbRepos], T]) -> T:
    """Run ``fn(repos)`` inside one short-lived session and transaction."""
    with db_scope() as repos:
        with db_transaction(repos.session):
            return fn(repos)
