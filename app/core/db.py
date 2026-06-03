"""SQLAlchemy engine, session lifecycle, and text-query helpers."""

from __future__ import annotations

import json
from collections.abc import Generator, Iterator
from contextlib import contextmanager
from functools import lru_cache
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings


@lru_cache
def _engine():
    return create_engine(settings.sqlalchemy_database_url, pool_pre_ping=True)


@lru_cache
def _session_factory():
    return sessionmaker(bind=_engine(), autoflush=False, autocommit=False)


def get_db_session() -> Generator[Session, None, None]:
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()


@contextmanager
def db_transaction(session: Session) -> Iterator[Session]:
    with session.begin():
        yield session


def parse_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _row_to_dict(row: Any, *, json_keys: frozenset[str] = frozenset()) -> dict[str, Any]:
    data = dict(row._mapping)
    for key in json_keys:
        if key in data:
            data[key] = parse_json(data[key])
    return data


def fetchone_dict(
    session: Session,
    sql: str,
    params: dict[str, Any],
    *,
    json_keys: frozenset[str] = frozenset(),
) -> dict[str, Any] | None:
    row = session.execute(text(sql), params).first()
    if row is None:
        return None
    return _row_to_dict(row, json_keys=json_keys)


def fetchall_dicts(
    session: Session,
    sql: str,
    params: dict[str, Any],
    *,
    json_keys: frozenset[str] = frozenset(),
) -> list[dict[str, Any]]:
    rows = session.execute(text(sql), params).all()
    return [_row_to_dict(row, json_keys=json_keys) for row in rows]


def execute_scalar(session: Session, sql: str, params: dict[str, Any]) -> Any:
    row = session.execute(text(sql), params).first()
    if row is None:
        return None
    return row[0]


@contextmanager
def db_scope() -> Iterator[Any]:
    from app.core.db_repos import build_db_repos

    session = _session_factory()()
    try:
        yield build_db_repos(session)
    finally:
        session.close()
