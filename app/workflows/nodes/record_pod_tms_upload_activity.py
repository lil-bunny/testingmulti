"""Workflow node: activity log transitions after TMS POD upload."""

from __future__ import annotations

from app.services.pod_tms_upload_activity import record_pod_tms_upload_from_state


def record_pod_tms_upload_activity(state):
    """Write TMS upload activity logs from ``turvo_upload_result`` in graph state."""
    record_pod_tms_upload_from_state(state)
    return state
