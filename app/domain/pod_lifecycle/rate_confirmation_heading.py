"""Match the exact Rate confirmation page title in extracted text."""

from __future__ import annotations

# Exact heading phrase (case-sensitive, including the space).
RATE_CONFIRMATION_NEEDLE = "Rate confirmation"


def page_has_rate_confirmation_heading(text: str) -> bool:
    """True when page text contains the exact ``Rate confirmation`` heading."""
    return RATE_CONFIRMATION_NEEDLE in (text or "")
