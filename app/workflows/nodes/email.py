import logging
from typing import Any, Dict, List

from app.services.pod_lifecycle.email_service import PodLifecycleEmailService
from app.tools.communication_metadata import stash_communication_id
from app.tools.email import detect_attachment_bytes_type
from app.tools.email import get_email_attachments as get_email_attachments_tool
from app.workflows.shipment_resolver import resolve_shipment_id

logger = logging.getLogger(__name__)


def send_email(state):
    result = PodLifecycleEmailService().send_pod_reminder_from_state(state)
    patch = result.to_state_patch()
    if result.send_result:
        stash_communication_id(state, result.send_result)
    elif result.communication_id:
        state.data["communication_id"] = result.communication_id
    state.data.update(patch)
    return state


def get_email_attachments(state):
    """Fetch Unipile attachment bytes; S3 upload happens in ``classify_attachments``."""
    attachments = state.data.get("attachments") or []
    email_id = state.data.get("email_id")
    account_id = PodLifecycleEmailService().resolve_sender_account_id(state)
    if not account_id:
        raise RuntimeError("missing_mikey_account_id: cannot fetch POD email attachments")
    attachments_ids = [attachment.get("id") for attachment in attachments]

    shipment_id = resolve_shipment_id(state.data)
    if not shipment_id:
        logger.warning("get_email_attachments: missing shipment_id")

    results: List[Dict[str, Any]] = []
    bytes_by_id: dict[str, bytes] = {}

    meta_by_id = {str(a.get("id")): a for a in attachments if a.get("id") is not None}

    for attachment_id in attachments_ids:
        meta = meta_by_id.get(str(attachment_id), {})
        original_filename = (
            meta.get("name")
            or meta.get("filename")
            or meta.get("file_name")
            or ""
        )
        try:
            file_content = get_email_attachments_tool(
                email_id=email_id,
                attachment_id=attachment_id,
                account_id=account_id,
            )
            if not file_content or len(file_content) == 0:
                results.append({
                    "attachment_id": attachment_id,
                    "success": False,
                    "object_key": None,
                    "error_message": "Attachment was empty or could not be retrieved.",
                    "original_filename": original_filename or None,
                    "document_id": None,
                    "stored_in_db": False,
                    "type": None,
                })
                continue

            extension, content_type = detect_attachment_bytes_type(file_content)
            att_id = str(attachment_id)
            bytes_by_id[att_id] = file_content

            results.append({
                "attachment_id": attachment_id,
                "object_key": None,
                "success": True,
                "content_type": content_type,
                "extension": extension,
                "error_message": None,
                "original_filename": original_filename or None,
                "document_id": None,
                "stored_in_db": False,
                "type": None,
                "file_bytes": file_content,
            })
        except Exception as e:
            error_msg = f"Error processing attachment {attachment_id}: {str(e)}"
            logger.exception(error_msg)
            results.append({
                "attachment_id": attachment_id,
                "success": False,
                "object_key": None,
                "error_message": str(e),
                "original_filename": original_filename or None,
                "document_id": None,
                "stored_in_db": False,
                "type": None,
            })

    state.data["get_email_attachments_results"] = results
    state.data["attachment_bytes_by_id"] = bytes_by_id
    state.data["pod_object_keys"] = []

    if any(not item.get("success", False) for item in results):
        failed_results = [item for item in results if not item.get("success", False)]
        failure_details = [
            {
                "attachment_id": item.get("attachment_id"),
                "error_message": item.get("error_message", "Attachment fetch failed"),
            }
            for item in failed_results
        ]
        raise RuntimeError(f"Attachment fetch failed: {failure_details}")

    return state
