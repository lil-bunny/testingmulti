import logging
from typing import Any, Dict, List, Tuple

from app.tools.email import get_email_attachments as get_email_attachments_tool, send_email as send_email_tool
from app.tools.email import ingest_email as ingest_email_tool
from app.services.reminder_scheduler import schedule_initial_pod_reminders
from app.services.s3bucket_service import bucket
from app.services.attachment_normalizer import pod_individual_attachment_filename
from app.models.document import DocumentType
from app.tools.documents import insert_document
from app.workflows.shipment_resolver import resolve_shipment_id

logger = logging.getLogger(__name__)

def send_email(state):
    send_email_tool(
        state.data.get("to"),
        state.data.get("subject", "POD Request"),
        state.data.get("body", "")
    )
    schedule_initial_pod_reminders(state.data)

    return state


def ingest_email(state):
    # result = ingest_email_tool(state.data)
    # state.data.update(result)

    return state


def check_email_attachments(state):
    attachments = state.data.get("attachments",[])
    has_attachments = state.data.get("has_attachments", False)
    if has_attachments is None:
        has_attachments = bool(attachments)

    state.data["is_pod_attached"] = has_attachments
    return state


def _detect_upload_type(file_content: bytes) -> Tuple[str, str]:
    """Infer extension and content type from file magic bytes."""
    if file_content.startswith(b"%PDF"):
        return "pdf", "application/pdf"
    if file_content.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if file_content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if file_content.startswith((b"GIF87a", b"GIF89a")):
        return "gif", "image/gif"
    if file_content.startswith(b"RIFF") and file_content[8:12] == b"WEBP":
        return "webp", "image/webp"
    return "bin", "application/octet-stream"


def get_email_attachments(state):
    """
    - fetch attachments using get_email_attachment tool
    - upload attachments to S3 and get URLs
    """
    attachments = state.data.get("attachments") or []
    email_id = state.data.get("email_id")
    account_id = state.data.get("account_id")
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
                    "uploaded_url": None,
                    "error_message": "Attachment was empty or could not be retrieved.",
                    "original_filename": original_filename or None,
                    "document_id": None,
                    "stored_in_db": False,
                    "type": None,
                })
                continue

            extension, content_type = _detect_upload_type(file_content)
            filename = pod_individual_attachment_filename(
                str(attachment_id), ship_token, extension
            )

            upload_result = bucket.upload_file(
                file_content=file_content,
                filename=filename,
                folder="pod_attachments",
                content_type=content_type,
                public=True,
            )
            uploaded_url = upload_result.get("file_url")
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
            if upload_success and uploaded_url:
                persist = insert_document(
                    DocumentType.POD_ATTACHMENT,
                    ship_token,
                    uploaded_url,
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
                "uploaded_url": uploaded_url,
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
                "uploaded_url": None,
                "error_message": str(e),
                "original_filename": original_filename or None,
                "document_id": None,
                "stored_in_db": False,
                "type": None,
            })

    pod_urls = [
        item["uploaded_url"]
        for item in results
        if item.get("success") and item.get("uploaded_url")
    ]

    state.data["get_email_attachments_results"] = results
    state.data["pod_urls"] = pod_urls
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