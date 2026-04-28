import hashlib
import logging
from typing import Any, Dict, List, Tuple

from app.tools.email import get_email_attachments as get_email_attachments_tool, send_email as send_email_tool
from app.tools.email import ingest_email as ingest_email_tool
from app.services.reminder_scheduler import schedule_initial_pod_reminders
from app.integrations.s3.bucket import bucket

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
    result = ingest_email_tool(state.data)

    state.data.update(result)

    return state


def check_email_attachments(state):
    attachments = state.data.get("attachments") or []
    has_attachments = state.data.get("has_attachments")
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

def _stable_attachment_token(attachment_id: str) -> str:
    """Create a filesystem-safe stable token for a source attachment id."""
    return hashlib.sha256(attachment_id.encode("utf-8")).hexdigest()

async def get_email_attachments(state):
    """
    - fetch attachments using get_email_attachment tool
    - upload attachments to S3 and get URLs
    """
    attachments = state.data.get("attachments") or []
    email_id = state.data.get("email_id")
    account_id = state.data.get("account_id")
    attachments_ids = [attachment.get("id") for attachment in attachments]

    results: List[Dict[str, Any]] = []

    for attachment_id in attachments_ids:
        try:
            file_content = await get_email_attachments_tool(
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
                })
                continue

            extension, content_type = _detect_upload_type(file_content)
            filename = f"pod_{attachment_id}.{extension}"
            
            upload_result = await bucket.upload_file(
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
                logger.warning(f"S3 upload returned None for attachment {attachment_id}")

            results.append({
                "attachment_id": attachment_id,
                "uploaded_url": uploaded_url,
                "success": upload_success,
                "content_type": content_type,
                "extension": extension,
                "error_message": upload_error,
            })
        except Exception as e:
            error_msg = f"Error processing attachment {attachment_id}: {str(e)}"
            logger.exception(error_msg)
            results.append({
                "attachment_id": attachment_id,
                "success": False,
                "uploaded_url": None,
                "error_message": str(e),
            })

    state.data["get_email_attachments_results"] = results
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