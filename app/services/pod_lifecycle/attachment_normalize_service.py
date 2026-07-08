"""Graph-path POD attachment merge/upload using ingress gate classifications."""

from __future__ import annotations

from typing import Any

from app.services.attachment_normalizer import AttachmentNormalizerService
from app.workflows.shipment_resolver import resolve_shipment_id


class PodAttachmentNormalizeService:
    """Merge/upload POD attachments; reuse ingress ``classification_by_attachment_id`` when set."""

    def __init__(
        self,
        *,
        normalizer: AttachmentNormalizerService | None = None,
    ) -> None:
        self._normalizer = normalizer or AttachmentNormalizerService()

    def normalize_from_state_data(self, data: dict[str, Any]) -> dict[str, Any]:
        pod_object_keys = data.get("pod_object_keys") or []
        shipment_id = resolve_shipment_id(data) or None

        prior: dict[str, dict] | None = None
        ingress_norm = data.get("attachment_normalization")
        if isinstance(ingress_norm, dict):
            raw_prior = ingress_norm.get("classification_by_attachment_id")
            if isinstance(raw_prior, dict) and raw_prior:
                prior = raw_prior

        result = self._normalizer.normalize(
            list(pod_object_keys),
            shipment_number=shipment_id,
            prior_classification_by_attachment_id=prior,
            upload_merged=True,
        )
        return result
