"""Workflow nodes for the ``ratecon`` template."""

from app.services.ratecon_document_service import RateconDocumentService


def cache_ratecon_page_count(state):
    """
    Download ratecon email attachments and cache PDF page count for POD strip.

    No S3 upload. Result is stored on ``state.data['ratecon_page_count_cache']``.
    """
    ratecon_document_service = RateconDocumentService()
    state.data["ratecon_page_count_cache"] = (
        ratecon_document_service.cache_from_email_attachments(state.data)
    )
    return state
