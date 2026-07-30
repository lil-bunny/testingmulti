"""Workflow nodes for the ``ratecon`` template."""

from app.services.ratecon_document_service import RateconDocumentService


def upload_ratecon_attachments(state):
    """
    Download ratecon email attachments, upload them, and persist ``documents`` rows.

    Result is stored on ``state.data['ratecon_s3_upload']``.
    """
    ratecon_document_service = RateconDocumentService()
    state.data["ratecon_s3_upload"] = ratecon_document_service.upload_email_attachments(
        state.data
    )
    return state
