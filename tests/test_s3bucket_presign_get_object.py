"""Tests for ``S3Bucket.presign_get_object``."""

from __future__ import annotations

from typing import Any

from app.services.s3bucket_service import S3Bucket


class _FakeS3Client:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def generate_presigned_url(
        self,
        ClientMethod: str,
        Params: dict[str, Any],
        ExpiresIn: int,
    ) -> str:
        self.calls.append(
            {
                "ClientMethod": ClientMethod,
                "Params": Params,
                "ExpiresIn": ExpiresIn,
            }
        )
        return f"https://example-bucket.test/presigned?key={Params['Key']}"


def test_presign_get_object_success():
    fake = _FakeS3Client()
    b = S3Bucket(s3_client=fake, bucket_name="my-bucket")
    out = b.presign_get_object("freightx/ratecon_attachments/ratecon_1000315335.pdf", expires_in=600)

    assert out["success"] is True
    assert out["error_message"] is None
    assert out["object_key"] == "freightx/ratecon_attachments/ratecon_1000315335.pdf"
    assert out["url"] == (
        "https://example-bucket.test/presigned?key=freightx/ratecon_attachments/ratecon_1000315335.pdf"
    )
    assert len(fake.calls) == 1
    assert fake.calls[0]["ClientMethod"] == "get_object"
    assert fake.calls[0]["Params"] == {
        "Bucket": "my-bucket",
        "Key": "freightx/ratecon_attachments/ratecon_1000315335.pdf",
    }
    assert fake.calls[0]["ExpiresIn"] == 600


def test_presign_get_object_rejects_url_as_key():
    fake = _FakeS3Client()
    b = S3Bucket(s3_client=fake, bucket_name="my-bucket")
    out = b.presign_get_object("https://example.com/file.pdf")

    assert out["success"] is False
    assert out["url"] is None
    assert "URL" in (out.get("error_message") or "")
    assert fake.calls == []


def test_presign_get_object_empty_key():
    fake = _FakeS3Client()
    b = S3Bucket(s3_client=fake, bucket_name="my-bucket")
    out = b.presign_get_object("  ")

    assert out["success"] is False
    assert out["error_message"] == "empty_object_key"
    assert fake.calls == []


def test_presign_get_object_without_s3_client():
    fake = _FakeS3Client()
    b = S3Bucket(s3_client=fake, bucket_name="my-bucket")
    b.s3_client = None
    out = b.presign_get_object("freightx/a.pdf")
    assert out["success"] is False
    assert "missing" in (out.get("error_message") or "").lower()


def test_presign_get_object_without_bucket_name():
    fake = _FakeS3Client()
    b = S3Bucket(s3_client=fake, bucket_name="my-bucket")
    b.bucket_name = None
    out = b.presign_get_object("freightx/a.pdf")
    assert out["success"] is False
    assert "missing" in (out.get("error_message") or "").lower()
