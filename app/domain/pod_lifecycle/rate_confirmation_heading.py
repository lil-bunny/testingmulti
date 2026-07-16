"""Match the Rate confirmation page title in extracted text."""

from __future__ import annotations

# Case-sensitive; compare after stripping whitespace (OCR often drops the space).
RATE_CONFIRMATION_NEEDLE = "Rateconfirmation"


def page_has_rate_confirmation_heading(text: str) -> bool:
    """True when compacted page text contains ``Rateconfirmation`` (case-sensitive)."""
    compact = "".join((text or "").split())
    return RATE_CONFIRMATION_NEEDLE in compact
