"""Workflow nodes for the ``ratecon`` template."""

from app.services.ratecon_document_service import RateconDocumentService


def upload_ratecon_attachments(state):
    """
    When the run includes Unipile attachment metadata + ``email_id``, download each
    file and upload to S3. Persists ``documents`` rows via ``RateconDocumentService``.
    Result is stored on ``state.data['ratecon_s3_upload']``.
    """
    state.data["ratecon_s3_upload"] = RateconDocumentService().upload_email_attachments(
        state.data
    )
    return state
