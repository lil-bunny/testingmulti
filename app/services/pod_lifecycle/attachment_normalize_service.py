"""Graph-path POD attachment merge/upload using ingress gate classifications."""

from __future__ import annotations

from typing import Any

from app.services.attachment_normalizer import AttachmentNormalizerService
from app.workflows.shipment_resolver import resolve_shipment_id


def attachment_bytes_by_id_from_state(data: dict[str, Any]) -> dict[str, bytes]:
    raw = data.get("attachment_bytes_by_id")
    if isinstance(raw, dict) and raw:
        return {
            str(att_id): file_bytes
            for att_id, file_bytes in raw.items()
            if att_id is not None and file_bytes
        }

    out: dict[str, bytes] = {}
    for item in data.get("get_email_attachments_results") or []:
        if not isinstance(item, dict) or not item.get("success"):
            continue
        att_id = str(item.get("attachment_id") or "").strip()
        file_bytes = item.get("file_bytes")
        if att_id and file_bytes:
            out[att_id] = file_bytes
    return out


class PodAttachmentNormalizeService:
    """Merge/upload POD attachments; reuse ingress ``classification_by_attachment_id`` when set."""

    def __init__(
        self,
        *,
        normalizer: AttachmentNormalizerService | None = None,
    ) -> None:
        self._normalizer = normalizer or AttachmentNormalizerService()

    def normalize_from_state_data(self, data: dict[str, Any]) -> dict[str, Any]:
        shipment_id = resolve_shipment_id(data) or None

        prior: dict[str, dict] | None = None
        ingress_norm = data.get("attachment_normalization")
        if isinstance(ingress_norm, dict):
            raw_prior = ingress_norm.get("classification_by_attachment_id")
            if isinstance(raw_prior, dict) and raw_prior:
                prior = raw_prior

        bytes_by_id = attachment_bytes_by_id_from_state(data)
        if bytes_by_id:
            return self._normalizer.normalize_from_bytes(
                bytes_by_id,
                shipment_number=shipment_id,
                prior_classification_by_attachment_id=prior,
                upload_merged=True,
            )

        pod_object_keys = data.get("pod_object_keys") or []
        return self._normalizer.normalize(
            list(pod_object_keys),
            shipment_number=shipment_id,
            prior_classification_by_attachment_id=prior,
            upload_merged=True,
        )
