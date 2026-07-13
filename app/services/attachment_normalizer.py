"""
POD attachment normalizer — port of old.services.attachment_normalizer.

Downloads attachment refs (HTTPS/S3) or in-memory bytes, classifies by MIME.
Assess-only mode stages accepted PDFs/images under a worker-local directory.
Merge/upload of staged files (or full normalize with upload_merged=True) produces
``pod_merged_pdf_object_key`` on S3.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
import img2pdf
from PIL import Image

from app.core.config import settings
from app.services.s3bucket_service import bucket, normalize_object_key
from app.tools.llm_client import chat_vision_json

logger = logging.getLogger(__name__)

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
    _HEIF_AVAILABLE = True
except ImportError:
    _HEIF_AVAILABLE = False

SUPPORTED_IMAGE_MIMES = {
    "image/jpeg",
    "image/png",
    "image/heic",
    "image/heif",
}

IMAGE_CLASSIFIER_SYSTEM_PROMPT = "Classify logistics document validity."

IMAGE_CLASSIFIER_USER_PROMPT = """You are a logistics document classifier. Analyze this image and determine if it is a valid logistics/shipping document.

**Valid (accept)**: BOL, POD, lumper receipt, warehouse receipt, weight ticket, packing slip, delivery ticket, dock receipt, signed document, photo of a document on a surface.
**Invalid (reject)**: Truck photo, selfie, company logo, email signature banner, map/directions screenshot, blank image, stock photo, meme.
**Borderline**: If uncertain, mark as valid with lower confidence.

Respond with ONLY valid JSON (no markdown, no code fences):
{"is_valid_document": true, "confidence": 0.92, "reasoning": "short reason", "detected_document_type": "BILL_OF_LADING"}"""

MIN_IMAGE_SIZE_BYTES = 10 * 1024
MIN_IMAGE_DIMENSION = 100


def _sanitize_path_segment(value: Optional[str]) -> str:
    """Filesystem / S3 key-safe token (shipment id, attachment id, etc.)."""
    if not value:
        return "unknown"
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "_", str(value).strip())
    return (cleaned or "unknown")[:180]


def pod_individual_attachment_filename(
    attachment_id: str, shipment_id: str, extension: str
) -> str:
    """S3 object basename: ``pod_{attachmentId}_{shipmentId}.{ext}``."""
    ext = (extension or "bin").lstrip(".").lower() or "bin"
    return (
        f"pod_{_sanitize_path_segment(attachment_id)}"
        f"_{_sanitize_path_segment(shipment_id)}.{ext}"
    )


def ratecon_shipment_object_basename(shipment_id: Optional[str]) -> str:
    """S3 object basename for ratecon uploads: ``ratecon_{shipmentId}.pdf`` (sanitized)."""
    return f"ratecon_{_sanitize_path_segment(shipment_id or 'unknown')}.pdf"


def pod_merged_filename(shipment_id: Optional[str]) -> str:
    """Final merged POD PDF basename: ``pod_{shipmentId}.pdf``."""
    return f"pod_{_sanitize_path_segment(shipment_id or 'unknown')}.pdf"


def in_memory_attachment_ref(
    attachment_id: str,
    shipment_number: str | None,
) -> str:
    """Synthetic S3 ref for in-memory normalize (must match ``normalize_from_bytes``)."""
    ship_token = _sanitize_path_segment(shipment_number or "unknown")
    att_token = _sanitize_path_segment(attachment_id)
    return f"{settings.BUCKET_POD_ATTACHMENTS_FOLDER}/pod_{att_token}_{ship_token}.bin"


class AttachmentNormalizerService:
    """Download, classify by type, merge POD attachments into a single PDF."""

    def normalize(
        self,
        pod_object_keys: List[str],
        shipment_number: Optional[str] = None,
        *,
        upload_merged: bool = True,
        local_merged_path: str | None = None,
        stage_dir: str | None = None,
        trace_metadata: dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        if trace_metadata:
            self._trace_metadata = dict(trace_metadata)
        if not pod_object_keys:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": [],
                "classification_results": [],
                "rejected": [],
                "source_attachments_cleanup": {"rejected": [], "valid_source": []},
                "error": "No pod_object_keys provided",
            }

        non_empty = [(u or "").strip() for u in pod_object_keys if (u or "").strip()]
        if len(non_empty) == 1:
            return self._with_classification_index(
                self._normalize_single_attachment(
                    non_empty[0],
                    shipment_number=shipment_number,
                    upload_merged=upload_merged,
                    local_merged_path=local_merged_path,
                    stage_dir=stage_dir,
                ),
                shipment_number,
            )

        valid_pdfs: List[Tuple[str, bytes]] = []
        valid_images: List[Tuple[str, bytes]] = []
        rejected: List[Dict[str, Any]] = []
        classification_results: List[Dict[str, Any]] = []
        source_attachment_ids: List[str] = []

        for raw in pod_object_keys:
            attachment_ref = (raw or "").strip()
            if not attachment_ref:
                continue

            attachment_id = self._extract_attachment_id(attachment_ref, shipment_number)
            if attachment_id:
                source_attachment_ids.append(attachment_id)

            file_bytes = self._download(attachment_ref)
            if not file_bytes:
                logger.error(
                    "attachment_normalizer.download_failed attachment_ref=%s",
                    attachment_ref,
                )
                rejected.append(
                    self._rejection_entry(attachment_ref, "download_failed", 1.0)
                )
                continue

            mime_type = self._detect_mime(file_bytes)
            logger.info(
                "attachment.type_detected attachment_ref=%s mime=%s size=%s",
                attachment_ref[:80],
                mime_type,
                len(file_bytes),
            )

            if mime_type == "application/pdf":
                valid_pdfs.append((attachment_ref, file_bytes))
                continue

            if mime_type in SUPPORTED_IMAGE_MIMES:
                image_bytes = self._normalize_image_bytes(file_bytes, mime_type)
                if image_bytes is None:
                    rejected.append(
                        self._rejection_entry(
                            attachment_ref, "image_conversion_failed", 1.0
                        )
                    )
                    continue

                prefilter = self._prefilter_image(image_bytes)
                if prefilter is not None:
                    rejected.append(
                        self._rejection_entry(attachment_ref, prefilter, 1.0)
                    )
                    classification_results.append(
                        {
                            "attachment_ref": attachment_ref,
                            "is_valid_document": False,
                            "confidence": 1.0,
                            "reasoning": prefilter,
                            "detected_document_type": None,
                            "prefiltered": True,
                        }
                    )
                    continue

                cls_result = self._classify_image(
                    image_bytes,
                    attachment_id=attachment_id,
                )
                cls_result["attachment_ref"] = attachment_ref
                classification_results.append(cls_result)

                if self._accept_image(cls_result):
                    valid_images.append((attachment_ref, image_bytes))
                else:
                    rejected.append(
                        self._rejection_entry(
                            attachment_ref,
                            cls_result.get("reasoning", "rejected_by_classifier"),
                            float(cls_result.get("confidence", 0.0)),
                        )
                    )
                continue

            logger.warning(
                "attachment_normalizer.unsupported_type attachment_ref=%s mime=%s",
                attachment_ref[:80],
                mime_type,
            )
            rejected.append(
                self._rejection_entry(
                    attachment_ref, f"unsupported_type: {mime_type}", 1.0
                )
            )

        if not valid_pdfs and not valid_images:
            return self._with_classification_index(
                {
                    "success": False,
                    "pod_merged_pdf_object_key": None,
                    "source_attachment_ids": source_attachment_ids,
                    "classification_results": classification_results,
                    "rejected": rejected,
                    "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                    "error": "No valid document attachments after classification",
                },
                shipment_number,
            )

        if not upload_merged:
            valid_source = [
                self._valid_source_entry(ref) for ref, _ in valid_pdfs
            ] + [self._valid_source_entry(ref) for ref, _ in valid_images]
            merge_paths, vision_paths = self._stage_accepted_files(
                valid_pdfs,
                valid_images,
                stage_dir=stage_dir,
                shipment_number=shipment_number,
            )
            out_assess: Dict[str, Any] = {
                "success": True,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {
                    "rejected": rejected,
                    "valid_source": valid_source,
                },
                "error": None,
                "assess_only": True,
                "pod_merge_source_paths": merge_paths,
                "pod_vision_image_paths": vision_paths,
            }
            return self._with_classification_index(out_assess, shipment_number)

        merged_bytes = self._merge_attachments(
            [pdf_bytes for _, pdf_bytes in valid_pdfs],
            [img_bytes for _, img_bytes in valid_images],
        )

        if merged_bytes is None:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": "PDF merge failed",
            }

        merged_filename = (
            pod_merged_filename(shipment_number)
            if shipment_number
            else f"pod_{self._deterministic_merged_id(source_attachment_ids)}.pdf"
        )

        logger.info(
            "attachments.merged pdf_count=%s image_count=%s bytes=%s file=%s shipment=%s",
            len(valid_pdfs),
            len(valid_images),
            len(merged_bytes),
            merged_filename,
            shipment_number,
        )

        upload_result = bucket.upload_file(
            file_content=merged_bytes,
            filename=merged_filename,
            folder=settings.BUCKET_POD_ATTACHMENTS_FOLDER,
            content_type="application/pdf",
        )
        pod_merged_pdf_object_key = upload_result.get("object_key") if upload_result.get("success") else None

        if not pod_merged_pdf_object_key:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": upload_result.get("error_message") or "Failed to upload merged PDF to S3",
            }

        local_path = self._write_local_merged_pdf(merged_bytes, local_merged_path)
        valid_source = [
            self._valid_source_entry(ref) for ref, _ in valid_pdfs
        ] + [self._valid_source_entry(ref) for ref, _ in valid_images]
        cleanup = {"rejected": rejected, "valid_source": valid_source}

        out: Dict[str, Any] = {
            "success": True,
            "pod_merged_pdf_object_key": pod_merged_pdf_object_key,
            "source_attachment_ids": source_attachment_ids,
            "classification_results": classification_results,
            "rejected": rejected,
            "source_attachments_cleanup": cleanup,
            "error": None,
        }
        if local_path:
            out["pod_merged_local_path"] = local_path
        return self._with_classification_index(out, shipment_number)

    def normalize_from_bytes(
        self,
        attachment_bytes_by_id: dict[str, bytes],
        *,
        shipment_number: str | None = None,
        upload_merged: bool = True,
        local_merged_path: str | None = None,
        stage_dir: str | None = None,
        trace_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not attachment_bytes_by_id:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": [],
                "classification_results": [],
                "classification_by_attachment_id": {},
                "rejected": [],
                "source_attachments_cleanup": {"rejected": [], "valid_source": []},
                "error": "No attachments provided",
            }

        refs: list[str] = []
        bytes_by_ref: dict[str, bytes] = {}
        for attachment_id, file_bytes in attachment_bytes_by_id.items():
            if not file_bytes:
                continue
            ref = in_memory_attachment_ref(attachment_id, shipment_number)
            refs.append(ref)
            bytes_by_ref[ref] = file_bytes

        if not refs:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": [],
                "classification_results": [],
                "classification_by_attachment_id": {},
                "rejected": [],
                "source_attachments_cleanup": {"rejected": [], "valid_source": []},
                "error": "No attachments provided",
            }

        processor = _InMemoryAttachmentNormalizer(bytes_by_ref)
        processor._trace_metadata = dict(trace_metadata or {})
        return processor.normalize(
            refs,
            shipment_number=shipment_number,
            upload_merged=upload_merged,
            local_merged_path=local_merged_path,
            stage_dir=stage_dir,
        )

    def merge_and_upload_staged(
        self,
        merge_source_paths: list[str],
        *,
        shipment_number: str | None = None,
        local_merged_path: str | None = None,
        source_attachment_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Merge worker-local staged files into one PDF and upload to S3."""
        paths = [str(p).strip() for p in merge_source_paths if str(p).strip()]
        if not paths:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "error": "No staged source paths provided",
            }

        pdf_bytes_list: list[bytes] = []
        image_bytes_list: list[bytes] = []
        for path in paths:
            try:
                file_bytes = Path(path).read_bytes()
            except OSError as exc:
                logger.error(
                    "attachment_normalizer.staged_read_failed path=%s err=%s",
                    path,
                    exc,
                )
                return {
                    "success": False,
                    "pod_merged_pdf_object_key": None,
                    "error": "staged_source_read_failed",
                }
            if not file_bytes:
                return {
                    "success": False,
                    "pod_merged_pdf_object_key": None,
                    "error": "staged_source_empty",
                }
            mime_type = self._detect_mime(file_bytes)
            if mime_type == "application/pdf":
                pdf_bytes_list.append(file_bytes)
            elif mime_type in SUPPORTED_IMAGE_MIMES:
                image_bytes = self._normalize_image_bytes(file_bytes, mime_type)
                if image_bytes is None:
                    return {
                        "success": False,
                        "pod_merged_pdf_object_key": None,
                        "error": "image_conversion_failed",
                    }
                image_bytes_list.append(image_bytes)
            else:
                return {
                    "success": False,
                    "pod_merged_pdf_object_key": None,
                    "error": f"unsupported_type: {mime_type}",
                }

        merged_bytes = self._merge_attachments(pdf_bytes_list, image_bytes_list)
        if merged_bytes is None:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "error": "PDF merge failed",
            }

        ids = [str(x).strip() for x in (source_attachment_ids or []) if str(x).strip()]
        merged_filename = (
            pod_merged_filename(shipment_number)
            if shipment_number
            else f"pod_{self._deterministic_merged_id(ids or paths)}.pdf"
        )
        logger.info(
            "attachments.merged_staged pdf_count=%s image_count=%s bytes=%s file=%s",
            len(pdf_bytes_list),
            len(image_bytes_list),
            len(merged_bytes),
            merged_filename,
        )
        upload_result = bucket.upload_file(
            file_content=merged_bytes,
            filename=merged_filename,
            folder=settings.BUCKET_POD_ATTACHMENTS_FOLDER,
            content_type="application/pdf",
        )
        object_key = (
            upload_result.get("object_key") if upload_result.get("success") else None
        )
        if not object_key:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "error": upload_result.get("error_message")
                or "Failed to upload merged PDF to S3",
            }

        local_path = self._write_local_merged_pdf(merged_bytes, local_merged_path)
        out: dict[str, Any] = {
            "success": True,
            "pod_merged_pdf_object_key": object_key,
            "error": None,
        }
        if local_path:
            out["pod_merged_local_path"] = local_path
        return out

    @staticmethod
    def _stage_accepted_files(
        valid_pdfs: List[Tuple[str, bytes]],
        valid_images: List[Tuple[str, bytes]],
        *,
        stage_dir: str | None,
        shipment_number: Optional[str],
    ) -> tuple[list[str], list[str]]:
        """Write accepted PDFs/images under stage_dir; return merge + vision paths."""
        root = (stage_dir or "").strip()
        if not root:
            return [], []
        sources = Path(root) / "sources"
        vision = Path(root) / "vision"
        try:
            sources.mkdir(parents=True, exist_ok=True)
            vision.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            logger.warning(
                "attachment_normalizer.stage_mkdir_failed dir=%s err=%s",
                root,
                exc,
            )
            return [], []

        merge_paths: list[str] = []
        vision_paths: list[str] = []
        index = 0
        for attachment_ref, pdf_bytes in valid_pdfs:
            index += 1
            att_id = (
                AttachmentNormalizerService._extract_attachment_id(
                    attachment_ref, shipment_number
                )
                or f"pdf{index}"
            )
            path = sources / f"{index:03d}_{_sanitize_path_segment(att_id)}.pdf"
            try:
                path.write_bytes(pdf_bytes)
            except OSError as exc:
                logger.warning(
                    "attachment_normalizer.stage_write_failed path=%s err=%s",
                    path,
                    exc,
                )
                continue
            merge_paths.append(str(path))

        for attachment_ref, image_bytes in valid_images:
            index += 1
            att_id = (
                AttachmentNormalizerService._extract_attachment_id(
                    attachment_ref, shipment_number
                )
                or f"img{index}"
            )
            # Prefer JPEG extension when bytes look like JPEG; else png/bin.
            ext = "jpg"
            if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
                ext = "png"
            path = sources / f"{index:03d}_{_sanitize_path_segment(att_id)}.{ext}"
            vision_path = vision / f"{index:03d}_{_sanitize_path_segment(att_id)}.{ext}"
            try:
                path.write_bytes(image_bytes)
                vision_path.write_bytes(image_bytes)
            except OSError as exc:
                logger.warning(
                    "attachment_normalizer.stage_write_failed path=%s err=%s",
                    path,
                    exc,
                )
                continue
            merge_paths.append(str(path))
            vision_paths.append(str(vision_path))

        return merge_paths, vision_paths

    @staticmethod
    def _write_local_merged_pdf(
        pdf_bytes: bytes,
        local_merged_path: str | None,
    ) -> str | None:
        """Write merged PDF to a worker-local path; never put bytes into graph state."""
        path = (local_merged_path or "").strip()
        if not path or not pdf_bytes:
            return None
        try:
            out = Path(path)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(pdf_bytes)
            return str(out)
        except Exception as exc:
            logger.warning(
                "attachment_normalizer.local_merged_write_failed path=%s err=%s",
                path,
                exc,
            )
            return None

    def _normalize_single_attachment(
        self,
        attachment_ref: str,
        shipment_number: Optional[str] = None,
        *,
        upload_merged: bool = True,
        local_merged_path: str | None = None,
        stage_dir: str | None = None,
    ) -> Dict[str, Any]:
        """
        Business rules for exactly one attachment:
        - PDF: skip merge pipeline; re-upload as ``pod_{shipmentId}.pdf`` for canonical naming.
        - Image: prefilter + classify; if accepted, convert to PDF and upload as ``pod_{shipmentId}.pdf``.
        """
        rejected: List[Dict[str, Any]] = []
        classification_results: List[Dict[str, Any]] = []
        attachment_id = self._extract_attachment_id(attachment_ref, shipment_number)
        source_attachment_ids = [attachment_id] if attachment_id else []

        file_bytes = self._download(attachment_ref)
        if not file_bytes:
            logger.error(
                "attachment_normalizer.single.download_failed attachment_ref=%s",
                attachment_ref,
            )
            rejected.append(
                self._rejection_entry(attachment_ref, "download_failed", 1.0)
            )
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": "download_failed",
                "single_attachment_short_circuit": True,
            }

        mime_type = self._detect_mime(file_bytes)
        logger.info(
            "attachment.single type=%s size=%s shipment=%s",
            mime_type,
            len(file_bytes),
            shipment_number,
        )

        merged_filename = (
            pod_merged_filename(shipment_number)
            if shipment_number
            else f"pod_{self._deterministic_merged_id(source_attachment_ids or [attachment_ref])}.pdf"
        )

        pdf_bytes: Optional[bytes] = None
        accepted_image_bytes: Optional[bytes] = None

        if mime_type == "application/pdf":
            pdf_bytes = file_bytes
        elif mime_type in SUPPORTED_IMAGE_MIMES:
            image_bytes = self._normalize_image_bytes(file_bytes, mime_type)
            if image_bytes is None:
                rejected.append(
                    self._rejection_entry(
                        attachment_ref, "image_conversion_failed", 1.0
                    )
                )
                return {
                    "success": False,
                    "pod_merged_pdf_object_key": None,
                    "source_attachment_ids": source_attachment_ids,
                    "classification_results": classification_results,
                    "rejected": rejected,
                    "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                    "error": "image_conversion_failed",
                    "single_attachment_short_circuit": True,
                }

            prefilter = self._prefilter_image(image_bytes)
            if prefilter is not None:
                rejected.append(
                    self._rejection_entry(attachment_ref, prefilter, 1.0)
                )
                classification_results.append(
                    {
                        "attachment_ref": attachment_ref,
                        "is_valid_document": False,
                        "confidence": 1.0,
                        "reasoning": prefilter,
                        "detected_document_type": None,
                        "prefiltered": True,
                    }
                )
                return {
                    "success": False,
                    "pod_merged_pdf_object_key": None,
                    "source_attachment_ids": source_attachment_ids,
                    "classification_results": classification_results,
                    "rejected": rejected,
                    "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                    "error": f"prefilter: {prefilter}",
                    "single_attachment_short_circuit": True,
                }

            cls_result = self._classify_image(
                image_bytes,
                attachment_id=attachment_id,
            )
            cls_result["attachment_ref"] = attachment_ref
            classification_results.append(cls_result)

            if not self._accept_image(cls_result):
                rejected.append(
                    self._rejection_entry(
                        attachment_ref,
                        cls_result.get("reasoning", "rejected_by_classifier"),
                        float(cls_result.get("confidence", 0.0)),
                    )
                )
                return {
                    "success": False,
                    "pod_merged_pdf_object_key": None,
                    "source_attachment_ids": source_attachment_ids,
                    "classification_results": classification_results,
                    "rejected": rejected,
                    "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                    "error": "rejected_by_classifier",
                    "single_attachment_short_circuit": True,
                }

            accepted_image_bytes = image_bytes
            if upload_merged:
                pdf_bytes = self._merge_attachments([], [image_bytes])
            else:
                pdf_bytes = b"%PDF-assess-placeholder"
        else:
            rejected.append(
                self._rejection_entry(
                    attachment_ref, f"unsupported_type: {mime_type}", 1.0
                )
            )
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": f"unsupported_type: {mime_type}",
                "single_attachment_short_circuit": True,
            }

        if not pdf_bytes:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": "pdf_build_failed",
                "single_attachment_short_circuit": True,
            }

        if not upload_merged:
            valid_pdfs: List[Tuple[str, bytes]] = []
            valid_images: List[Tuple[str, bytes]] = []
            if mime_type == "application/pdf":
                valid_pdfs = [(attachment_ref, file_bytes)]
            elif accepted_image_bytes is not None:
                valid_images = [(attachment_ref, accepted_image_bytes)]
            merge_paths, vision_paths = self._stage_accepted_files(
                valid_pdfs,
                valid_images,
                stage_dir=stage_dir,
                shipment_number=shipment_number,
            )
            return self._with_classification_index(
                {
                    "success": True,
                    "pod_merged_pdf_object_key": None,
                    "source_attachment_ids": source_attachment_ids,
                    "classification_results": classification_results,
                    "rejected": rejected,
                    "source_attachments_cleanup": {
                        "rejected": rejected,
                        "valid_source": [self._valid_source_entry(attachment_ref)],
                    },
                    "error": None,
                    "single_attachment_short_circuit": True,
                    "assess_only": True,
                    "pod_merge_source_paths": merge_paths,
                    "pod_vision_image_paths": vision_paths,
                },
                shipment_number,
            )

        upload_result = bucket.upload_file(
            file_content=pdf_bytes,
            filename=merged_filename,
            folder=settings.BUCKET_POD_ATTACHMENTS_FOLDER,
            content_type="application/pdf",
        )
        pod_merged_pdf_object_key = upload_result.get("object_key") if upload_result.get("success") else None

        if not pod_merged_pdf_object_key:
            return {
                "success": False,
                "pod_merged_pdf_object_key": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": upload_result.get("error_message")
                or "Failed to upload merged PDF to S3",
                "single_attachment_short_circuit": True,
            }

        local_path = self._write_local_merged_pdf(pdf_bytes, local_merged_path)
        valid_source = [self._valid_source_entry(attachment_ref)]
        cleanup = {"rejected": rejected, "valid_source": valid_source}

        out: Dict[str, Any] = {
            "success": True,
            "pod_merged_pdf_object_key": pod_merged_pdf_object_key,
            "source_attachment_ids": source_attachment_ids,
            "classification_results": classification_results,
            "rejected": rejected,
            "source_attachments_cleanup": cleanup,
            "error": None,
            "single_attachment_short_circuit": True,
        }
        if local_path:
            out["pod_merged_local_path"] = local_path
        return out

    def _classify_image(
        self,
        image_bytes: bytes,
        *,
        attachment_id: str | None = None,
    ) -> Dict[str, Any]:
        """Classify image via shared traced ``chat_vision_json`` (LangSmith LLM span)."""
        api_key = settings.LLM_API_KEY
        if not api_key:
            logger.warning(
                "attachment.classify_llm_skip attachment_id=%s reason=no_api_key",
                attachment_id or "-",
            )
            return {
                "is_valid_document": True,
                "confidence": 0.0,
                "reasoning": "no_classifier_api_key_configured",
                "detected_document_type": None,
                "prefiltered": False,
            }

        model = (
            settings.ATTACHMENT_CLASSIFIER_MODEL
            or settings.LLM_MODEL
        )

        mime = "image/jpeg"
        if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            mime = "image/png"

        logger.info(
            "attachment.classify_llm_start attachment_id=%s model=%s bytes=%s mime=%s",
            attachment_id or "-",
            model,
            len(image_bytes),
            mime,
        )
        started = time.monotonic()

        base_meta = dict(getattr(self, "_trace_metadata", {}) or {})
        if attachment_id:
            base_meta["attachment_id"] = attachment_id
        base_meta.setdefault("step_key", "pod_attachment_classifier")
        # LangSmith thread grouping: prefer lifecycle id, else execution id.
        thread_id = (
            str(base_meta.get("workflow_lifecycle_id") or "").strip()
            or str(base_meta.get("execution_id") or "").strip()
        )
        if thread_id:
            base_meta["thread_id"] = thread_id

        try:
            result = chat_vision_json(
                IMAGE_CLASSIFIER_SYSTEM_PROMPT,
                IMAGE_CLASSIFIER_USER_PROMPT,
                image_bytes,
                temperature=0.1,
                max_tokens=150,
                model=model,
                image_mime_type=mime,
                timeout_s=60.0,
                metadata=base_meta,
                tags=["pod_attachment_classifier"],
            )
            elapsed_ms = (time.monotonic() - started) * 1000

            logger.info(
                "attachment.classify_llm_done attachment_id=%s is_valid=%s "
                "confidence=%s doc_type=%s ms=%.0f",
                attachment_id or "-",
                result.get("is_valid_document"),
                result.get("confidence"),
                result.get("detected_document_type"),
                elapsed_ms,
            )

            return {
                "is_valid_document": result.get("is_valid_document", True),
                "confidence": float(result.get("confidence", 0.5)),
                "reasoning": result.get("reasoning", ""),
                "detected_document_type": result.get("detected_document_type"),
                "prefiltered": False,
            }

        except Exception as e:
            elapsed_ms = (time.monotonic() - started) * 1000
            logger.exception(
                "attachment.classify_llm_error attachment_id=%s ms=%.0f err=%s",
                attachment_id or "-",
                elapsed_ms,
                e,
            )
            return {
                "is_valid_document": True,
                "confidence": 0.0,
                "reasoning": f"classification_error: {e}",
                "detected_document_type": None,
                "prefiltered": False,
            }

    def _merge_attachments(
        self,
        pdf_bytes_list: List[bytes],
        image_bytes_list: List[bytes],
    ) -> Optional[bytes]:
        try:
            from pikepdf import Pdf

            merged = Pdf.new()

            for pdf_data in pdf_bytes_list:
                src = Pdf.open(io.BytesIO(pdf_data))
                merged.pages.extend(src.pages)

            if image_bytes_list:
                images_pdf_bytes = img2pdf.convert(image_bytes_list)
                images_pdf = Pdf.open(io.BytesIO(images_pdf_bytes))
                merged.pages.extend(images_pdf.pages)

            if len(merged.pages) == 0:
                logger.warning("attachment_normalizer.merge_empty")
                return None

            buf = io.BytesIO()
            merged.save(buf)
            return buf.getvalue()

        except Exception as e:
            logger.exception("attachment_normalizer.merge_failed: %s", e)
            return None

    @staticmethod
    def _download(attachment_ref: str) -> Optional[bytes]:
        """Fetch bytes from an HTTPS source or a private S3 object key."""
        raw = (attachment_ref or "").strip()
        if not raw:
            return None
        if raw.startswith(("http://", "https://")):
            try:
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(raw)
                    resp.raise_for_status()
                    if not resp.content:
                        return None
                    return resp.content
            except Exception as e:
                logger.error(
                    "attachment_normalizer.download_error attachment_ref=%s err=%s",
                    raw[:80],
                    e,
                )
                return None
        got = bucket.download_object_bytes(raw)
        if got.get("success") and got.get("body"):
            return got["body"]
        logger.error(
            "attachment_normalizer.s3_download_failed object_key=%s err=%s",
            raw[:120],
            got.get("error_message"),
        )
        return None

    @staticmethod
    def _detect_mime(file_bytes: bytes) -> str:
        if file_bytes.startswith(b"%PDF"):
            return "application/pdf"
        if file_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if file_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if file_bytes.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if len(file_bytes) >= 12 and file_bytes.startswith(b"RIFF") and file_bytes[8:12] == b"WEBP":
            return "image/webp"
        if len(file_bytes) >= 12 and file_bytes[4:8] == b"ftyp":
            brand = file_bytes[8:16].lower()
            if b"heic" in brand or b"heix" in brand or b"mif1" in brand:
                return "image/heic"
        return "application/octet-stream"

    @staticmethod
    def _normalize_image_bytes(file_bytes: bytes, mime_type: str) -> Optional[bytes]:
        if mime_type in ("image/heic", "image/heif"):
            if not _HEIF_AVAILABLE:
                logger.error("attachment_normalizer.pillow_heif_not_available")
                return None
            try:
                img = Image.open(io.BytesIO(file_bytes))
                buf = io.BytesIO()
                img.convert("RGB").save(buf, format="JPEG", quality=95)
                return buf.getvalue()
            except Exception as e:
                logger.error("attachment_normalizer.heic_convert_error: %s", e)
                return None
        return file_bytes

    @staticmethod
    def _prefilter_image(image_bytes: bytes) -> Optional[str]:
        if len(image_bytes) < MIN_IMAGE_SIZE_BYTES:
            return "too_small"
        try:
            img = Image.open(io.BytesIO(image_bytes))
            w, h = img.size
            if w < MIN_IMAGE_DIMENSION or h < MIN_IMAGE_DIMENSION:
                return "tiny_dimensions"
        except Exception:
            return "corrupt_image"
        return None

    @staticmethod
    def _accept_image(cls_result: Dict[str, Any]) -> bool:
        return bool(cls_result.get("is_valid_document", False))

    @staticmethod
    def _with_classification_index(
        result: Dict[str, Any],
        shipment_number: Optional[str],
    ) -> Dict[str, Any]:
        by_id: Dict[str, Dict[str, Any]] = {}
        for row in result.get("classification_results") or []:
            if not isinstance(row, dict):
                continue
            ref = str(row.get("attachment_ref") or "").strip()
            if not ref:
                continue
            att_id = AttachmentNormalizerService._extract_attachment_id(
                ref, shipment_number
            )
            if not att_id:
                continue
            by_id[att_id] = {
                k: v for k, v in row.items() if k != "attachment_ref"
            }
        if by_id:
            result["classification_by_attachment_id"] = by_id
        elif "classification_by_attachment_id" not in result:
            result["classification_by_attachment_id"] = {}
        return result

    @staticmethod
    def _extract_attachment_id(
        attachment_ref: str, shipment_hint: Optional[str] = None
    ) -> Optional[str]:
        """Derive attachment id token from an S3 object key or an HTTP(S) attachment path."""
        ref = (attachment_ref or "").strip()
        if ref.startswith(("http://", "https://")):
            path = (urlparse(ref).path or "").lstrip("/")
            key = path
        else:
            try:
                key = normalize_object_key(ref)
            except ValueError:
                return None
        base = key.rstrip("/").rsplit("/", 1)[-1]
        if not base or "." not in base:
            m = re.search(rf"{settings.BUCKET_POD_ATTACHMENTS_FOLDER}/pod_([^.]+)\.\w+$", key)
            return m.group(1) if m else None
        stem, _, _ext = base.rpartition(".")
        if not stem.startswith("pod_"):
            m = re.search(rf"{settings.BUCKET_POD_ATTACHMENTS_FOLDER}/pod_([^.]+)\.\w+$", key)
            return m.group(1) if m else None
        rest = stem[4:]
        if shipment_hint:
            ship_s = _sanitize_path_segment(shipment_hint)
            suffix = f"_{ship_s}"
            if rest.endswith(suffix) and len(rest) > len(suffix):
                return rest[: -len(suffix)]
        if "_" in rest:
            att_part, _ship_part = rest.rsplit("_", 1)
            return att_part or None
        return rest or None

    @staticmethod
    def _deterministic_merged_id(source_ids: List[str]) -> str:
        if not source_ids:
            return uuid.uuid4().hex
        canonical = "|".join(sorted(source_ids))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _rejection_entry(
        attachment_ref: str, reason: str, confidence: float
    ) -> Dict[str, Any]:
        ref = (attachment_ref or "").strip()
        if ref.startswith(("http://", "https://")):
            object_key = ""
        else:
            try:
                object_key = normalize_object_key(ref)
            except ValueError:
                object_key = ""
        return {
            "attachment_ref": ref,
            "object_key": object_key,
            "rejection_reason": reason,
            "confidence": confidence,
            "classified_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _valid_source_entry(
        attachment_ref: str, reason: str = "merged_into_final_pdf"
    ) -> Dict[str, Any]:
        ref = (attachment_ref or "").strip()
        if ref.startswith(("http://", "https://")):
            object_key = ""
        else:
            try:
                object_key = normalize_object_key(ref)
            except ValueError:
                object_key = ""
        return {
            "attachment_ref": ref,
            "object_key": object_key,
            "reason": reason,
            "flagged_at": datetime.now(timezone.utc).isoformat(),
        }


class _InMemoryAttachmentNormalizer(AttachmentNormalizerService):
    """Assess-only normalizer: ``_download`` reads pre-fetched bytes by ref."""

    def __init__(self, bytes_by_ref: dict[str, bytes]) -> None:
        self._bytes_by_ref = bytes_by_ref

    def _download(self, attachment_ref: str) -> Optional[bytes]:
        return self._bytes_by_ref.get((attachment_ref or "").strip())
