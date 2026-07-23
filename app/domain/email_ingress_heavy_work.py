"""
Edge Heavy-Work Gate: cheap, metadata-only check for whether an inbound Unipile
email needs Heavy Ingress Work deferred to the Pre-Lifecycle Work Queue, instead
of running inline on the HTTP edge.

Usecase-shaped, not tenant-shaped: register new heavy attachment kinds here
(any tenant) rather than duplicating this check per tenant ingress service.
Metadata only (names/extensions) — never fetches attachment bytes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.domain.gelita.email_attachments import (
    is_delivery_locations_attachment,
    is_load_tendering_attachment,
)
from app.domain.unipile_email_attachments import (
    attachment_display_name,
    iter_unipile_xlsx_attachments,
)

# Predicates over an attachment *file name*. A payload needs Heavy Ingress Work
# when any attachment name matches any registered predicate. Add future heavy
# kinds (any tenant, any attachment shape) here rather than teaching the HTTP
# edge about new tenant ingress services.
HEAVY_ATTACHMENT_NAME_PREDICATES: tuple[Callable[[str | None], bool], ...] = (
    is_delivery_locations_attachment,
    is_load_tendering_attachment,
)


def payload_requires_heavy_ingress_work(payload: dict[str, Any]) -> bool:
    """
    True when this inbound email's attachments match the Heavy Ingress Work catalog.

    Metadata-only (attachment name/extension); never fetches attachment bytes.
    Callers should still run this after `has_attachments` is known true to skip
    the scan cheaply.
    """
    if not payload.get("has_attachments"):
        return False

    for attachment in iter_unipile_xlsx_attachments(payload):
        file_name = attachment_display_name(attachment)
        if any(predicate(file_name) for predicate in HEAVY_ATTACHMENT_NAME_PREDICATES):
            return True

    return False
