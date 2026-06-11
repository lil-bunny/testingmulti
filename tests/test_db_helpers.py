"""Tests for SQLAlchemy db helpers."""

from __future__ import annotations

from unittest.mock import MagicMock

from app.core.db import fetchall_dicts, fetchone_dict, parse_json


def test_parse_json_dict_passthrough():
    assert parse_json({"a": 1}) == {"a": 1}


def test_parse_json_string():
    assert parse_json('{"x": 2}') == {"x": 2}


def test_parse_json_empty():
    assert parse_json(None) == {}
    assert parse_json("") == {}
    assert parse_json("not-json") == {}


def test_fetchone_dict_maps_row():
    session = MagicMock()
    row = MagicMock()
    row._mapping = {"id": "abc", "metadata": {"k": 1}}
    session.execute.return_value.first.return_value = row

    out = fetchone_dict(session, "SELECT 1", {}, json_keys=frozenset({"metadata"}))
    assert out == {"id": "abc", "metadata": {"k": 1}}


def test_fetchone_dict_none():
    session = MagicMock()
    session.execute.return_value.first.return_value = None
    assert fetchone_dict(session, "SELECT 1", {}) is None


def test_fetchall_dicts():
    session = MagicMock()
    row1 = MagicMock()
    row1._mapping = {"id": "1"}
    row2 = MagicMock()
    row2._mapping = {"id": "2"}
    session.execute.return_value.all.return_value = [row1, row2]

    out = fetchall_dicts(session, "SELECT 1", {})
    assert out == [{"id": "1"}, {"id": "2"}]
