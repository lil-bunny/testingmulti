"""Shared POD lifecycle sub-status guards."""

from __future__ import annotations

from app.models.status import StatusSubType

POD_PROCESSING_COMPLETE_SUB_STATUSES = frozenset(
    {
        StatusSubType.DOCUMENT_PROCESSED,
        StatusSubType.UPLOADED_TO_TMS,
        StatusSubType.RESOLVED_MANUALLY,
    }
)


def is_pod_processing_complete_sub_status(sub: StatusSubType | None) -> bool:
    """True when POD extraction pipeline finished (duplicate email gate)."""
    return sub in POD_PROCESSING_COMPLETE_SUB_STATUSES
