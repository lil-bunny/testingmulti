"""Synthetic ``pod_lifecycle`` / ``email_received`` payloads for opt-in mail-free E2E."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.models.workflow_run_event_type import WorkflowRunEventType


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _resolve_fixture_path(raw: str) -> Path:
    path = Path(raw.strip())
    if not path.is_absolute():
        path = _repo_root() / path
    return path.resolve()


def attachment_fixture_map_from_env() -> dict[str, str]:
    raw = _env("POD_E2E_ATTACHMENT_FIXTURES")
    if raw:
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise ValueError("POD_E2E_ATTACHMENT_FIXTURES must be a JSON object")
        return {str(k).strip(): str(v).strip() for k, v in parsed.items() if str(k).strip()}
    single = _env("POD_E2E_ATTACHMENT_FIXTURE_PATH")
    if single:
        return {"att-e2e-pod-1": single}
    return {"att-e2e-pod-1": "tests/fixtures/testpod.pdf"}


def _attachment_meta(attachment_id: str, fixture_path: str) -> dict[str, Any]:
    path = _resolve_fixture_path(fixture_path)
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "pdf":
        mime = "application/pdf"
    elif suffix in ("png", "jpg", "jpeg", "gif", "webp"):
        mime = f"image/{'jpeg' if suffix == 'jpg' else suffix}"
    else:
        mime = "application/octet-stream"
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {
        "id": attachment_id,
        "name": path.name,
        "extension": suffix or "bin",
        "size": size,
        "mime": mime,
    }


def pod_email_e2e_correlation() -> dict[str, str] | None:
    """Required env keys for full-stack POD email E2E; ``None`` if incomplete."""
    keys = {
        "tenant_slug": _env("POD_E2E_TENANT_SLUG") or "t3ra",
        "shipments_row_id": _env("POD_E2E_SHIPMENTS_ROW_ID"),
        "shipment_id": _env("POD_E2E_SHIPMENT_ID"),
        "thread_id": _env("POD_E2E_THREAD_ID"),
        "ratecon_workflow_lifecycle_id": _env("POD_E2E_RATECON_LC_ID"),
    }
    missing = [k for k, v in keys.items() if k != "tenant_slug" and not v]
    if missing:
        return None
    return keys  # type: ignore[return-value]


def build_pod_email_received_payload(
    correlation: dict[str, str],
    *,
    execution_id: str | None = None,
) -> dict[str, Any]:
    """``email_received`` payload for ``run_workflow_async`` (Celery-direct E2E)."""
    fixture_map = attachment_fixture_map_from_env()
    attachments = [
        _attachment_meta(att_id, fixture_path)
        for att_id, fixture_path in fixture_map.items()
    ]
    payload: dict[str, Any] = {
        "event_type": WorkflowRunEventType.EMAIL_RECEIVED.value,
        "event": "mail_received",
        "email_id": _env("POD_E2E_EMAIL_ID") or "e2e-synthetic-email-1",
        "account_id": _env("POD_E2E_ACCOUNT_ID") or "e2e-synthetic-account-1",
        "thread_id": correlation["thread_id"],
        "shipments_row_id": correlation["shipments_row_id"],
        "shipment_id": correlation["shipment_id"],
        "ratecon_workflow_lifecycle_id": correlation["ratecon_workflow_lifecycle_id"],
        "has_attachments": True,
        "subject": _env("POD_E2E_SUBJECT")
        or f"Re: Rate confirmation for shipment #{correlation['shipment_id']}",
        "in_reply_to": {
            "message_id": "<e2e-parent-message@freightx.ai>",
            "id": "e2e-parent-email-id",
        },
        "from_attendee": {
            "display_name": "E2E Driver",
            "identifier": "e2e-driver@freightx.ai",
            "identifier_type": "EMAIL_ADDRESS",
        },
        "to_attendees": [
            {
                "display_name": "FreightX",
                "identifier": "ayush@freightx.ai",
                "identifier_type": "EMAIL_ADDRESS",
            }
        ],
        "attachments": attachments,
    }
    if execution_id:
        payload["execution_id"] = execution_id
    return payload
