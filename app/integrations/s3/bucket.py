import asyncio
import boto3
import logging
from typing import Any, Dict
from urllib.parse import urlparse
from app.core.config import settings

# module logger
logger = logging.getLogger(__name__)

class S3Bucket:
    """S3-compatible bucket utility for file operations (AWS S3 or DO Spaces)"""

    # Global prefix for all uploads
    BUCKET_PREFIX = "freightx"

    def __init__(self):
        """Initialize S3-compatible client"""
        self.s3_client = None
        self.bucket_name = None
        self._init_client()

    def _init_client(self):
        """Initialize S3-compatible client (AWS S3 or Digital Ocean Spaces)"""
        try:
            # Check if using AWS S3 (no custom endpoint) or DO Spaces (custom endpoint)
            endpoint_url = settings.BUCKET_ENDPOINT if settings.BUCKET_ENDPOINT else None

            self.s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.BUCKET_ID,
                aws_secret_access_key=settings.BUCKET_KEY,
                endpoint_url=endpoint_url,
                region_name=getattr(settings, 'BUCKET_REGION', 'us-west-2')
            )

            # Use explicit bucket name if configured, otherwise extract from endpoint
            self.bucket_name = getattr(settings, 'BUCKET_NAME', None)
            if not self.bucket_name and endpoint_url:
                # For DO Spaces: extract from endpoint (e.g., bucket.nyc3.digitaloceanspaces.com)
                endpoint_domain = urlparse(endpoint_url).netloc
                self.bucket_name = endpoint_domain.split('.')[0]
            
        except Exception:
            # Log the failure to initialize S3 client
            logger.exception("Failed to initialize S3 client")
            self.s3_client = None
            self.bucket_name = None

    async def upload_file(
        self,
        file_content: bytes,
        filename: str,
        content_type: str,
        folder: str = "pod_attachments",
        public: bool = True
    ) -> Dict[str, Any]:
        """Upload file content to S3 bucket.

        Args:
            file_content: Binary content of the file
            filename: Original filename
            folder: Folder path in the bucket (default: pod_attachments)
            content_type: MIME type of the file
            public: Whether the file should be publicly accessible

        Returns:
            Upload result with success status, file URL, and error message.
        """
        try:           
            if not self.s3_client or not self.bucket_name:
                error_msg = "S3 client not initialized or bucket name missing"
                return {
                    "success": False,
                    "file_url": None,
                    "error_message": error_msg,
                }

            # Use the original filename with global prefix
            unique_filename = f"{self.BUCKET_PREFIX}/{folder}/{filename}"

            # Prepare upload args. Public access is controlled by bucket policy or CDN,
            # because buckets with Object Ownership enforced reject per-object ACLs.
            put_args = {
                'Bucket': self.bucket_name,
                'Key': unique_filename,
                'Body': file_content,
                'ContentType': content_type,
            }

            # Upload to S3
            await asyncio.to_thread(self.s3_client.put_object, **put_args)

            # Generate public URL
            if settings.BUCKET_ENDPOINT:
                # Custom endpoint (DO Spaces) - bucket might be in domain
                file_url = f"{settings.BUCKET_ENDPOINT}/{unique_filename}"
            else:
                # AWS S3 - use standard URL format
                region = getattr(settings, 'BUCKET_REGION', 'us-west-2')
                file_url = f"https://{self.bucket_name}.s3.{region}.amazonaws.com/{unique_filename}"

            return {
                "success": True,
                "file_url": file_url,
                "error_message": None,
            }

        except Exception as e:
            error_msg = f"Error uploading file to S3: {filename} - {str(e)}"
            logger.exception(error_msg)
            return {
                "success": False,
                "file_url": None,
                "error_message": error_msg,
            }

    async def delete_file(self, file_url: str) -> Dict[str, Any]:
        """Delete a file from S3 bucket using its URL.

        Args:
            file_url: The complete URL of the file to delete

        Returns:
            Deletion result with success status, file URL, and error message.
        """
        try:
            if not self.s3_client or not self.bucket_name:
                error_msg = "S3 client not initialized or bucket name missing"
                return {
                    "success": False,
                    "file_url": file_url,
                    "error_message": error_msg,
                }

            # Parse the URL to extract the key
            parsed_url = urlparse(file_url)

            # Extract the path from the URL (remove leading slash)
            object_key = parsed_url.path.lstrip('/')

            # Delete the object
            await asyncio.to_thread(
                self.s3_client.delete_object,
                Bucket=self.bucket_name,
                Key=object_key
            )

            return {
                "success": True,
                "file_url": file_url,
                "error_message": None,
            }
                
        except Exception as e:
            error_msg = f"Error deleting file from S3: {file_url} - {str(e)}"
            logger.exception(error_msg)
            return {
                "success": False,
                "file_url": file_url,
                "error_message": error_msg,
            }

# Global instance
bucket = S3Bucket()