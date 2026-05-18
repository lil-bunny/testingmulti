"""Load tendering workflow nodes."""

from __future__ import annotations

from typing import Any

from app.core.logger import get_logger

logger = get_logger(__name__)


def log_load_tendering_context(state):
    d = state.data
    row = d.get("tender_row")
    order_preview: Any = ""
    if isinstance(row, dict):
        order_preview = row.get("order_number") or ""
    logger.info(
        "load_tendering: event_type=%r webhook_name=%r source_email_thread_id=%s "
        "data_import_id=%s tender_row_index=%s order_number_preview=%s load_id=%s "
        "execution_id=%s workflow_lifecycle_id=%s",
        d.get("event_type"),
        d.get("webhook_name"),
        d.get("source_email_thread_id"),
        d.get("data_import_id"),
        d.get("tender_row_index"),
        order_preview,
        d.get("load_id"),
        d.get("execution_id"),
        d.get("workflow_lifecycle_id"),
    )
    return state
