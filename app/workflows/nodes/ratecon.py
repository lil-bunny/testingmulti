"""Workflow nodes for the ``ratecon`` template."""

from app.core.logger import get_logger
from app.models.document import DocumentType
from app.tools.documents import insert_document
from app.tools.ratecon import upload_ratecon_email_attachments_to_s3
from app.workflows.shipment_resolver import (
    resolve_shipment_id,
    resolve_shipments_row_id_for_db,
)

logger = get_logger(__name__)


def upload_ratecon_attachments(state):
    """
    When the run includes Unipile attachment metadata + ``email_id``, download each
    file and upload to S3. Persists ``documents`` rows via ``insert_document``.
    Result is stored on ``state.data['ratecon_s3_upload']``.
    """
    attachments = state.data.get("attachments") or []
    if not attachments:
        out = {"skipped": True, "reason": "no_attachments"}
        state.data["ratecon_s3_upload"] = out
        logger.info("[ratecon] S3 upload %s", out)
        return state

    email_id = state.data.get("email_id")
    if email_id is None or not str(email_id).strip():
        out = {
            "skipped": True,
            "reason": "missing_email_id",
            "attachment_count": len(attachments),
        }
        state.data["ratecon_s3_upload"] = out
        logger.info("[ratecon] S3 upload %s", out)
        return state

    shipment_id = resolve_shipment_id(state.data)
    if not shipment_id:
        out = {
            "skipped": True,
            "reason": "missing_shipment_id",
            "attachment_count": len(attachments),
        }
        state.data["ratecon_s3_upload"] = out
        logger.warning("[ratecon] S3 upload %s", out)
        return state

    account_id = state.data.get("account_id")
    result = upload_ratecon_email_attachments_to_s3(
        email_id=str(email_id).strip(),
        account_id=str(account_id).strip() if account_id else None,
        attachments=list(attachments),
        shipment_id=str(shipment_id),
    )
    eid = state.data.get("email_id")
    eid_s = str(eid).strip() if eid is not None else None
    for item in result.get("results") or []:
        if not item.get("success") or not item.get("object_key"):
            item["document_persist"] = {
                "stored": False,
                "skipped": True,
                "reason": "no_successful_upload_or_object_key",
            }
            continue
        aid = item.get("attachment_id")
        shipments_row_id = resolve_shipments_row_id_for_db(state.data)
        if not shipments_row_id:
            item["document_persist"] = {
                "stored": False,
                "skipped": True,
                "reason": "missing_shipments_row_id",
            }
            logger.warning(
                "[ratecon] skip document persist: missing shipments_row_id shipment_id=%s",
                shipment_id,
            )
            continue
        persist = insert_document(
            DocumentType.RATECON,
            storage_key=str(item["object_key"]),
            shipments_row_id=shipments_row_id,
            email_id=eid_s,
            attachment_id=str(aid) if aid is not None else None,
        )
        item["document_persist"] = {
            "stored": bool(persist.get("stored")),
            "id": persist.get("id"),
            "error": persist.get("error"),
        }
    state.data["ratecon_s3_upload"] = result
    logger.info("[ratecon] S3 upload finished: %s", result)
    return state
