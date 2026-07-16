"""Match the Rate confirmation page title in extracted text."""

from __future__ import annotations

# Case-sensitive phrase after stripping whitespace ("Rate confirmation" / OCR "Rateconfirmation").
RATE_CONFIRMATION_NEEDLE = "Rateconfirmation"


def page_has_rate_confirmation_heading(text: str) -> bool:
    """
    True when page text contains ``Rate confirmation`` (case-sensitive).

    Whitespace is removed before matching so OCR that drops the space still hits.
    """
    compact = "".join((text or "").split())
    return RATE_CONFIRMATION_NEEDLE in compact
