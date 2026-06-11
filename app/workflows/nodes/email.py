import logging
from typing import Any, Dict, List

from app.core.config import settings
from app.domain.pod_lifecycle_settings import resolve_pod_sender_account_id
from app.services.unipile_service import UnipileException
from app.tools.communication_metadata import stash_communication_id
from app.tools.email import detect_attachment_bytes_type
from app.tools.email import get_email_attachments as get_email_attachments_tool, send_email as send_email_tool
from app.services.s3bucket_service import bucket
from app.services.attachment_normalizer import pod_individual_attachment_filename
from app.models.document import DocumentType
from app.tools.documents import insert_document
from app.workflows.shipment_resolver import (
    resolve_shipment_id,
    resolve_shipments_row_id_for_db,
)

logger = logging.getLogger(__name__)


def send_email(state):
    tenant_raw = getattr(state, "tenant_id", None) or state.data.get("tenant_id")
    run_id = str(state.execution_id or "").strip() or None
    sender_account_id = resolve_pod_sender_account_id(state)
    if not sender_account_id:
        logger.error(
            "send_email: mikey_account_id not configured lifecycle_id=%s shipment_id=%s",
            state.data.get("workflow_lifecycle_id"),
            state.data.get("shipment_id"),
        )
        state.data["pod_reminder_error"] = "missing_mikey_account_id"
        state.data["pod_reminder_sent"] = False
        return state

    send_result = None
    try:
        send_result = send_email_tool(
            state.data.get("to"),
            state.data.get("subject", "POD Request"),
            state.data.get("body", ""),
            thread_id=state.data.get("thread_id"),
            account_id=sender_account_id,
            tenant_id=tenant_raw,
            workflow_run_id=run_id,
            communication_metadata={
                "source": "pod_send_email",
                "thread_id": state.data.get("thread_id"),
                "email_id": state.data.get("email_id"),
                "workflow_lifecycle_id": state.data.get("workflow_lifecycle_id"),
                "shipment_id": state.data.get("shipment_id"),
            },
        )
    except UnipileException as exc:
        logger.warning(
            "send_email Unipile error lifecycle_id=%s shipment_id=%s: %s",
            state.data.get("workflow_lifecycle_id"),
            state.data.get("shipment_id"),
            exc,
        )
        state.data["pod_reminder_result"] = send_result
        state.data["pod_reminder_error"] = str(exc)
        state.data["pod_reminder_sent"] = False
        return state
    except Exception:
        logger.exception(
            "send_email unexpected error lifecycle_id=%s shipment_id=%s",
            state.data.get("workflow_lifecycle_id"),
            state.data.get("shipment_id"),
        )
        state.data["pod_reminder_result"] = send_result
        state.data["pod_reminder_error"] = "unexpected_error"
        state.data["pod_reminder_sent"] = False
        return state

    if send_result is None:
        state.data["pod_reminder_error"] = "send_skipped_or_no_result"
        state.data["pod_reminder_sent"] = False
        return state

    stash_communication_id(
        state,
        send_result if isinstance(send_result, dict) else None,
    )
    state.data["pod_reminder_result"] = send_result
    success = True
    if isinstance(send_result, dict):
        success = bool(send_result.get("success", True))
    state.data["pod_reminder_sent"] = success
    if not success:
        state.data["pod_reminder_error"] = (
            (send_result or {}).get("error") if isinstance(send_result, dict) else None
        ) or "unipile_send_failed"
    return state


def get_email_attachments(state):
    """
    - fetch attachments using get_email_attachment tool
    - upload attachments to S3 and persist object keys (use ``presign_get_object`` to expose links)
    """
    attachments = state.data.get("attachments") or []
    email_id = state.data.get("email_id")
    account_id = resolve_pod_sender_account_id(state)
    if not account_id:
        raise RuntimeError("missing_mikey_account_id: cannot fetch POD email attachments")
    attachments_ids = [attachment.get("id") for attachment in attachments]

    shipment_id = resolve_shipment_id(state.data)
    if not shipment_id:
        logger.warning("get_email_attachments: missing shipment_id; using 'unknown' in object names")
    ship_token = shipment_id or "unknown"

    results: List[Dict[str, Any]] = []

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
                account_id=account_id
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
            filename = pod_individual_attachment_filename(
                str(attachment_id), ship_token, extension
            )

            upload_result = bucket.upload_file(
                file_content=file_content,
                filename=filename,
                folder=settings.BUCKET_POD_ATTACHMENTS_FOLDER,
                content_type=content_type,
            )
            uploaded_key = upload_result.get("object_key")
            upload_success = bool(upload_result.get("success"))
            upload_error = upload_result.get("error_message")

            if not upload_success:
                logger.warning(
                    "get_email_attachments: S3 upload failed attachment_id=%s err=%s",
                    attachment_id,
                    upload_error,
                )
            # DB
            document_id = None
            stored_in_db = False
            doc_row_type = None
            if upload_success and uploaded_key:
                persist = insert_document(
                    DocumentType.POD_ATTACHMENT,
                    storage_key=uploaded_key,
                    shipments_row_id=resolve_shipments_row_id_for_db(state.data),
                    email_id=email_id,
                    attachment_id=str(attachment_id)
                    if attachment_id is not None
                    else None,
                )
                stored_in_db = bool(persist.get("stored"))
                document_id = persist.get("id") if stored_in_db else None
                doc_row_type = persist.get("type") if stored_in_db else None
                if not stored_in_db:
                    logger.warning(
                        "get_email_attachments: documents insert failed attachment_id=%s err=%s",
                        attachment_id,
                        persist.get("error"),
                    )

            results.append({
                "attachment_id": attachment_id,
                "object_key": uploaded_key,
                "success": upload_success,
                "content_type": content_type,
                "extension": extension,
                "error_message": upload_error,
                "original_filename": original_filename or None,
                "document_id": document_id,
                "stored_in_db": stored_in_db,
                "type": doc_row_type,
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

    pod_object_keys = [
        item["object_key"]
        for item in results
        if item.get("success") and item.get("object_key")
    ]

    state.data["get_email_attachments_results"] = results
    state.data["pod_object_keys"] = pod_object_keys
    if any(not item.get("success", False) for item in results):
        failed_results = [item for item in results if not item.get("success", False)]
        failure_details = [
            {
                "attachment_id": item.get("attachment_id"),
                "error_message": item.get("error_message", "Attachment upload failed"),
            }
            for item in failed_results
        ]
        raise RuntimeError(f"Attachment upload failed: {failure_details}")
 
    return state