"""
POD attachment normalizer — port of old.services.attachment_normalizer.

Downloads each URL, classifies by MIME: PDFs pass through; images are
prefiltered then optionally vision-classified; unsupported types rejected.
Valid PDFs and images merge into one PDF and upload to S3.

**Single attachment:** PDFs skip merge/classifier and are re-uploaded as
``pod_{shipmentId}.pdf``. Images use the same classify + PDF conversion path
as multi-attachment flows, then upload as ``pod_{shipmentId}.pdf``.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import httpx
import img2pdf
from openai import OpenAI
from PIL import Image

from app.core.config import settings
from app.services.s3bucket_service import bucket

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


def pod_merged_filename(shipment_id: Optional[str]) -> str:
    """Final merged POD PDF basename: ``pod_{shipmentId}.pdf``."""
    return f"pod_{_sanitize_path_segment(shipment_id or 'unknown')}.pdf"


class AttachmentNormalizerService:
    """Download, classify by type, merge POD attachments into a single PDF."""

    def normalize(
        self,
        pod_urls: List[str],
        shipment_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not pod_urls:
            return {
                "success": False,
                "merged_pdf_url": None,
                "source_attachment_ids": [],
                "classification_results": [],
                "rejected": [],
                "source_attachments_cleanup": {"rejected": [], "valid_source": []},
                "error": "No pod_urls provided",
            }

        non_empty = [(u or "").strip() for u in pod_urls if (u or "").strip()]
        if len(non_empty) == 1:
            return self._normalize_single_attachment(
                non_empty[0], shipment_number=shipment_number
            )

        valid_pdfs: List[Tuple[str, bytes]] = []
        valid_images: List[Tuple[str, bytes]] = []
        rejected: List[Dict[str, Any]] = []
        classification_results: List[Dict[str, Any]] = []
        source_attachment_ids: List[str] = []

        for url in pod_urls:
            url = (url or "").strip()
            if not url:
                continue

            attachment_id = self._extract_attachment_id(url, shipment_number)
            if attachment_id:
                source_attachment_ids.append(attachment_id)

            file_bytes = self._download(url)
            if not file_bytes:
                logger.error("attachment_normalizer.download_failed url=%s", url)
                rejected.append(self._rejection_entry(url, "download_failed", 1.0))
                continue

            mime_type = self._detect_mime(file_bytes)
            logger.info(
                "attachment.type_detected url=%s mime=%s size=%s",
                url[:80],
                mime_type,
                len(file_bytes),
            )

            if mime_type == "application/pdf":
                valid_pdfs.append((url, file_bytes))
                continue

            if mime_type in SUPPORTED_IMAGE_MIMES:
                image_bytes = self._normalize_image_bytes(file_bytes, mime_type)
                if image_bytes is None:
                    logger.warning("attachment_normalizer.heic_conversion_failed url=%s", url)
                    rejected.append(self._rejection_entry(url, "image_conversion_failed", 1.0))
                    continue

                prefilter = self._prefilter_image(image_bytes)
                if prefilter is not None:
                    logger.info("attachment.prefilter_rejected url=%s reason=%s", url, prefilter)
                    rejected.append(self._rejection_entry(url, prefilter, 1.0))
                    classification_results.append(
                        {
                            "url": url,
                            "is_valid_document": False,
                            "confidence": 1.0,
                            "reasoning": prefilter,
                            "detected_document_type": None,
                            "prefiltered": True,
                        }
                    )
                    continue

                cls_result = self._classify_image(image_bytes)
                cls_result["url"] = url
                classification_results.append(cls_result)

                if self._accept_image(cls_result):
                    valid_images.append((url, image_bytes))
                else:
                    rejected.append(
                        self._rejection_entry(
                            url,
                            cls_result.get("reasoning", "rejected_by_classifier"),
                            float(cls_result.get("confidence", 0.0)),
                        )
                    )
                continue

            logger.warning(
                "attachment_normalizer.unsupported_type url=%s mime=%s", url[:80], mime_type
            )
            rejected.append(self._rejection_entry(url, f"unsupported_type: {mime_type}", 1.0))

        if not valid_pdfs and not valid_images:
            return {
                "success": False,
                "merged_pdf_url": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": "No valid document attachments after classification",
            }

        merged_bytes = self._merge_attachments(
            [pdf_bytes for _, pdf_bytes in valid_pdfs],
            [img_bytes for _, img_bytes in valid_images],
        )

        if merged_bytes is None:
            return {
                "success": False,
                "merged_pdf_url": None,
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
            folder="pod_attachments",
            content_type="application/pdf",
            public=True,
        )
        merged_pdf_url = upload_result.get("file_url") if upload_result.get("success") else None

        if not merged_pdf_url:
            return {
                "success": False,
                "merged_pdf_url": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": upload_result.get("error_message") or "Failed to upload merged PDF to S3",
            }

        valid_source = [self._valid_source_entry(u) for u, _ in valid_pdfs] + [
            self._valid_source_entry(u) for u, _ in valid_images
        ]
        cleanup = {"rejected": rejected, "valid_source": valid_source}

        return {
            "success": True,
            "merged_pdf_url": merged_pdf_url,
            "source_attachment_ids": source_attachment_ids,
            "classification_results": classification_results,
            "rejected": rejected,
            "source_attachments_cleanup": cleanup,
            "error": None,
        }

    def _normalize_single_attachment(
        self,
        url: str,
        shipment_number: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Business rules for exactly one attachment:
        - PDF: skip merge pipeline; re-upload as ``pod_{shipmentId}.pdf`` for canonical naming.
        - Image: prefilter + classify; if accepted, convert to PDF and upload as ``pod_{shipmentId}.pdf``.
        """
        rejected: List[Dict[str, Any]] = []
        classification_results: List[Dict[str, Any]] = []
        attachment_id = self._extract_attachment_id(url, shipment_number)
        source_attachment_ids = [attachment_id] if attachment_id else []

        file_bytes = self._download(url)
        if not file_bytes:
            logger.error("attachment_normalizer.single.download_failed url=%s", url)
            rejected.append(self._rejection_entry(url, "download_failed", 1.0))
            return {
                "success": False,
                "merged_pdf_url": None,
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
            else f"pod_{self._deterministic_merged_id(source_attachment_ids or [url])}.pdf"
        )

        pdf_bytes: Optional[bytes] = None

        if mime_type == "application/pdf":
            pdf_bytes = file_bytes
        elif mime_type in SUPPORTED_IMAGE_MIMES:
            image_bytes = self._normalize_image_bytes(file_bytes, mime_type)
            if image_bytes is None:
                rejected.append(self._rejection_entry(url, "image_conversion_failed", 1.0))
                return {
                    "success": False,
                    "merged_pdf_url": None,
                    "source_attachment_ids": source_attachment_ids,
                    "classification_results": classification_results,
                    "rejected": rejected,
                    "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                    "error": "image_conversion_failed",
                    "single_attachment_short_circuit": True,
                }

            prefilter = self._prefilter_image(image_bytes)
            if prefilter is not None:
                rejected.append(self._rejection_entry(url, prefilter, 1.0))
                classification_results.append(
                    {
                        "url": url,
                        "is_valid_document": False,
                        "confidence": 1.0,
                        "reasoning": prefilter,
                        "detected_document_type": None,
                        "prefiltered": True,
                    }
                )
                return {
                    "success": False,
                    "merged_pdf_url": None,
                    "source_attachment_ids": source_attachment_ids,
                    "classification_results": classification_results,
                    "rejected": rejected,
                    "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                    "error": f"prefilter: {prefilter}",
                    "single_attachment_short_circuit": True,
                }

            cls_result = self._classify_image(image_bytes)
            cls_result["url"] = url
            classification_results.append(cls_result)

            if not self._accept_image(cls_result):
                rejected.append(
                    self._rejection_entry(
                        url,
                        cls_result.get("reasoning", "rejected_by_classifier"),
                        float(cls_result.get("confidence", 0.0)),
                    )
                )
                return {
                    "success": False,
                    "merged_pdf_url": None,
                    "source_attachment_ids": source_attachment_ids,
                    "classification_results": classification_results,
                    "rejected": rejected,
                    "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                    "error": "rejected_by_classifier",
                    "single_attachment_short_circuit": True,
                }

            pdf_bytes = self._merge_attachments([], [image_bytes])
        else:
            rejected.append(
                self._rejection_entry(url, f"unsupported_type: {mime_type}", 1.0)
            )
            return {
                "success": False,
                "merged_pdf_url": None,
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
                "merged_pdf_url": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": "pdf_build_failed",
                "single_attachment_short_circuit": True,
            }

        upload_result = bucket.upload_file(
            file_content=pdf_bytes,
            filename=merged_filename,
            folder="pod_attachments",
            content_type="application/pdf",
            public=True,
        )
        merged_pdf_url = upload_result.get("file_url") if upload_result.get("success") else None

        if not merged_pdf_url:
            return {
                "success": False,
                "merged_pdf_url": None,
                "source_attachment_ids": source_attachment_ids,
                "classification_results": classification_results,
                "rejected": rejected,
                "source_attachments_cleanup": {"rejected": rejected, "valid_source": []},
                "error": upload_result.get("error_message")
                or "Failed to upload merged PDF to S3",
                "single_attachment_short_circuit": True,
            }

        valid_source = [self._valid_source_entry(url)]
        cleanup = {"rejected": rejected, "valid_source": valid_source}

        return {
            "success": True,
            "merged_pdf_url": merged_pdf_url,
            "source_attachment_ids": source_attachment_ids,
            "classification_results": classification_results,
            "rejected": rejected,
            "source_attachments_cleanup": cleanup,
            "error": None,
            "single_attachment_short_circuit": True,
        }

    def _classify_image(self, image_bytes: bytes) -> Dict[str, Any]:
        api_key = settings.LLM_API_KEY
        if not api_key:
            logger.warning("attachment_normalizer.no_classifier_key; accepting image")
            return {
                "is_valid_document": True,
                "confidence": 0.0,
                "reasoning": "no_classifier_api_key_configured",
                "detected_document_type": None,
                "prefiltered": False,
            }

        base_url = settings.LLM_BASE_URL
        model = (
            settings.ATTACHMENT_CLASSIFIER_MODEL
            or settings.LLM_MODEL
        )

        try:
            client = OpenAI(api_key=api_key, base_url=base_url)
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            mime = "image/jpeg"
            if image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"

            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": IMAGE_CLASSIFIER_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": IMAGE_CLASSIFIER_USER_PROMPT},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:{mime};base64,{b64}",
                                    "detail": "low",
                                },
                            },
                        ],
                    },
                ],
                max_tokens=150,
                temperature=0.1,
            )

            raw_text = (response.choices[0].message.content or "").strip()
            result = json.loads(raw_text)

            logger.info(
                "attachment.classified is_valid=%s confidence=%s",
                result.get("is_valid_document"),
                result.get("confidence"),
            )

            return {
                "is_valid_document": result.get("is_valid_document", True),
                "confidence": float(result.get("confidence", 0.5)),
                "reasoning": result.get("reasoning", ""),
                "detected_document_type": result.get("detected_document_type"),
                "prefiltered": False,
            }

        except Exception as e:
            logger.exception("attachment_normalizer.classify_error: %s", e)
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
    def _download(url: str) -> Optional[bytes]:
        try:
            with httpx.Client(timeout=30.0) as client:
                resp = client.get(url)
                resp.raise_for_status()
                if not resp.content:
                    return None
                return resp.content
        except Exception as e:
            logger.error("attachment_normalizer.download_error url=%s err=%s", url[:80], e)
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
        if cls_result.get("is_valid_document", True):
            return True
        confidence = float(cls_result.get("confidence", 0.0))
        return confidence < 0.7

    @staticmethod
    def _extract_attachment_id(
        url: str, shipment_hint: Optional[str] = None
    ) -> Optional[str]:
        """Derive attachment id token from our S3 URL basename."""
        parsed = urlparse(url)
        path = parsed.path or ""
        base = path.rstrip("/").rsplit("/", 1)[-1]
        if not base or "." not in base:
            m = re.search(r"/pod_attachments/pod_([^.]+)\.\w+$", url)
            return m.group(1) if m else None
        stem, _, _ext = base.rpartition(".")
        if not stem.startswith("pod_"):
            m = re.search(r"/pod_attachments/pod_([^.]+)\.\w+$", url)
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
    def _rejection_entry(url: str, reason: str, confidence: float) -> Dict[str, Any]:
        parsed = urlparse(url)
        s3_key = parsed.path.lstrip("/")
        return {
            "attachment_url": url,
            "s3_key": s3_key,
            "rejection_reason": reason,
            "confidence": confidence,
            "classified_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _valid_source_entry(
        url: str, reason: str = "merged_into_final_pdf"
    ) -> Dict[str, Any]:
        parsed = urlparse(url)
        s3_key = parsed.path.lstrip("/")
        return {
            "attachment_url": url,
            "s3_key": s3_key,
            "reason": reason,
            "flagged_at": datetime.now(timezone.utc).isoformat(),
        }
