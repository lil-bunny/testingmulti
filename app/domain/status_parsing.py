"""Map DB lifecycle / activity status strings to typed enums."""

from __future__ import annotations

from app.models.status import StatusSubType, StatusType


def status_type_from_db(raw: str | None) -> StatusType | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return StatusType(str(raw).strip())
    except ValueError:
        return None


def sub_status_type_from_db(raw: str | None) -> StatusSubType | None:
    if raw is None or not str(raw).strip():
        return None
    try:
        return StatusSubType(str(raw).strip())
    except ValueError:
        return None
