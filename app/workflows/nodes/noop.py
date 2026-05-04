"""Lightweight routing nodes."""

from __future__ import annotations


def noop_pod_followup_marker(state):
    """Next send_email is the process_pod branch (POD still missing)."""
    state.data["_pod_email_context"] = "process_pod_followup"
    return state
