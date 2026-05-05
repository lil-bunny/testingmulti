import boto3
import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from app.core.config import settings

logger = logging.getLogger(__name__)


def normalize_object_key(key: str) -> str:
    """Return a trimmed S3 object key. Rejects URLs and other non-key values."""
    raw = (key or "").strip().lstrip("/")
    if not raw:
        return ""
    if raw.startswith(("http://", "https://")) or "://" in raw:
        raise ValueError("expected S3 object key, not a URL")
    return raw


class S3Bucket:
    """S3-compatible bucket utility for file operations (AWS S3 or DO Spaces)."""

    BUCKET_PREFIX = "freightx"

    def __init__(self, s3_client=None, bucket_name=None):
        self.s3_client = s3_client
        self.bucket_name = bucket_name
        if not self.s3_client:
            self._init_client()

    def _init_client(self):
        try:
            endpoint_url = settings.BUCKET_ENDPOINT if settings.BUCKET_ENDPOINT else None

            self.s3_client = boto3.client(
                "s3",
                aws_access_key_id=settings.BUCKET_ID,
                aws_secret_access_key=settings.BUCKET_KEY,
                endpoint_url=endpoint_url,
                region_name=getattr(settings, "BUCKET_REGION", "us-west-2"),
            )

            self.bucket_name = getattr(settings, "BUCKET_NAME", None)
            if not self.bucket_name and endpoint_url:
                endpoint_domain = urlparse(endpoint_url).netloc
                self.bucket_name = endpoint_domain.split(".")[0]

        except Exception:
            logger.exception("Failed to initialize S3 client")
            self.s3_client = None
            self.bucket_name = None

    def upload_file(
        self,
        file_content: bytes,
        filename: str,
        content_type: str,
        folder: str = "pod_attachments",
    ) -> Dict[str, Any]:
        """Upload bytes to the bucket (private objects). Persist the returned ``object_key``."""
        try:
            if not self.s3_client or not self.bucket_name:
                error_msg = "S3 client not initialized or bucket name missing"
                return {
                    "success": False,
                    "object_key": None,
                    "error_message": error_msg,
                }

            object_key = f"{self.BUCKET_PREFIX}/{folder}/{filename}"

            put_args: Dict[str, Any] = {
                "Bucket": self.bucket_name,
                "Key": object_key,
                "Body": file_content,
                "ContentType": content_type,
            }

            self.s3_client.put_object(**put_args)

            return {
                "success": True,
                "object_key": object_key,
                "error_message": None,
            }

        except Exception as e:
            error_msg = f"Error uploading file to S3: {filename} - {str(e)}"
            logger.exception(error_msg)
            return {
                "success": False,
                "object_key": None,
                "error_message": error_msg,
            }

    def presign_get_object(
        self,
        object_key: str,
        expires_in: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a time-limited HTTPS URL for ``GetObject`` (private bucket)."""
        try:
            if not self.s3_client or not self.bucket_name:
                return {
                    "success": False,
                    "url": None,
                    "object_key": None,
                    "error_message": "S3 client not initialized or bucket name missing",
                }
            key = normalize_object_key(object_key)
            if not key:
                return {
                    "success": False,
                    "url": None,
                    "object_key": None,
                    "error_message": "empty_object_key",
                }
            ttl = (
                expires_in
                if expires_in is not None
                else int(settings.BUCKET_PRESIGN_EXPIRES_SECONDS)
            )
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": key},
                ExpiresIn=ttl,
            )
            return {
                "success": True,
                "url": url,
                "object_key": key,
                "error_message": None,
            }
        except ValueError as e:
            return {
                "success": False,
                "url": None,
                "object_key": None,
                "error_message": str(e),
            }
        except Exception as e:
            logger.exception("presign_get_object failed object_key=%r", object_key)
            return {
                "success": False,
                "url": None,
                "object_key": None,
                "error_message": str(e),
            }

    def download_object_bytes(self, object_key: str) -> Dict[str, Any]:
        """Download object body using app credentials."""
        try:
            if not self.s3_client or not self.bucket_name:
                return {
                    "success": False,
                    "body": None,
                    "object_key": None,
                    "error_message": "S3 client not initialized or bucket name missing",
                }
            key = normalize_object_key(object_key)
            if not key:
                return {
                    "success": False,
                    "body": None,
                    "object_key": None,
                    "error_message": "empty_object_key",
                }
            resp = self.s3_client.get_object(Bucket=self.bucket_name, Key=key)
            body = resp["Body"].read()
            return {
                "success": True,
                "body": body,
                "object_key": key,
                "error_message": None,
            }
        except ValueError as e:
            return {
                "success": False,
                "body": None,
                "object_key": None,
                "error_message": str(e),
            }
        except Exception as e:
            logger.exception("download_object_bytes failed object_key=%r", object_key)
            return {
                "success": False,
                "body": None,
                "object_key": None,
                "error_message": str(e),
            }

    def delete_file(self, object_key: str) -> Dict[str, Any]:
        """Delete an object by S3 object key."""
        try:
            if not self.s3_client or not self.bucket_name:
                error_msg = "S3 client not initialized or bucket name missing"
                return {
                    "success": False,
                    "object_key": object_key,
                    "error_message": error_msg,
                }

            key = normalize_object_key(object_key)
            self.s3_client.delete_object(Bucket=self.bucket_name, Key=key)

            return {
                "success": True,
                "object_key": key,
                "error_message": None,
            }

        except ValueError as e:
            return {
                "success": False,
                "object_key": object_key,
                "error_message": str(e),
            }
        except Exception as e:
            error_msg = f"Error deleting file from S3: {object_key} - {str(e)}"
            logger.exception(error_msg)
            return {
                "success": False,
                "object_key": object_key,
                "error_message": error_msg,
            }

def public_url_for_object_key(object_key: str) -> str:
    """
    Public GET URL for an S3 key, matching URL rules in ``S3Bucket.upload_file``.

    Used when ``documents`` stores only ``object_key`` (e.g. ratecon rows) so readers
    still get a download URL without persisting it.
    """
    key = (object_key or "").strip().lstrip("/")
    if not key:
        return ""
    if settings.BUCKET_ENDPOINT:
        return f"{str(settings.BUCKET_ENDPOINT).rstrip('/')}/{key}"
    bucket_name = getattr(settings, "BUCKET_NAME", None) or ""
    region = getattr(settings, "BUCKET_REGION", "us-west-2")
    if not bucket_name:
        return ""
    return f"https://{bucket_name}.s3.{region}.amazonaws.com/{key}"


# Global instance
bucket = S3Bucket()
