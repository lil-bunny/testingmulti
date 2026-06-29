"""Tests for ``PackType`` enum helpers."""

from __future__ import annotations

from app.models.pack_type import PackType


def test_pack_type_parse_normalizes_case() -> None:
    assert PackType.parse("BAG") == PackType.BAG
    assert PackType.parse(" drum ") == PackType.DRUM
    assert PackType.parse("Bag") == PackType.BAG
    assert PackType.parse("Case") == PackType.CASE
    assert PackType.parse("Pail") == PackType.PAIL


def test_pack_type_plural_nouns() -> None:
    assert PackType.BAG.plural_noun() == "bags"
    assert PackType.DRUM.plural_noun() == "drums"
    assert PackType.JAR.plural_noun() == "jars"
    assert PackType.CASE.plural_noun() == "cases"
    assert PackType.PAIL.plural_noun() == "pails"
