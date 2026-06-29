"""Pack-code pack type (``pack_codes.pack_type`` PostgreSQL enum)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class PackType(StrEnum):
    BAG = "bag"
    DRUM = "drum"
    JAR = "jar"
    CASE = "case"
    PAIL = "pail"

    @classmethod
    def parse(cls, val: Any) -> PackType | None:
        """Coerce DB, CSV, or API values to ``PackType``; used by calc and email."""
        if val is None:
            return None
        if isinstance(val, PackType):
            return val
        text = str(val).strip().lower()
        if not text:
            return None
        try:
            return cls(text)
        except ValueError:
            return None

    def plural_noun(self) -> str:
        """Plural noun for tender email piece lines (e.g. bag → bags)."""
        return _PLURAL_NOUNS[self]


_PLURAL_NOUNS: dict[PackType, str] = {
    PackType.BAG: "bags",
    PackType.DRUM: "drums",
    PackType.JAR: "jars",
    PackType.CASE: "cases",
    PackType.PAIL: "pails",
}
