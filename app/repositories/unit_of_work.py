"""Shared DB connection scope for multi-table commits."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from app.core.config import settings


@contextmanager
def unit_of_work() -> Iterator[psycopg.Connection]:
    """
    Yield one connection; commit on clean exit, rollback on exception.
    """
    conn = psycopg.connect(settings.DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
