"""
Upload a local rate confirmation PDF to S3 using S3Bucket (same layout as POD uploads).

Default: reads repo-root carrier_rate_confirmation.pdf and stores it as
freightx/pod_attachments/ratecon_1000324868.pdf

Usage (from new/):
  python scripts/upload_ratecon_to_s3.py

Or with explicit paths:
  python scripts/upload_ratecon_to_s3.py --source /path/to/file.pdf --folder pod_attachments

Requires .env in new/ with BUCKET_* settings (same as the app).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.s3bucket_service import bucket  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload rate con PDF to S3 via S3Bucket.")
    default_source = ROOT.parent / "carrier_rate_confirmation.pdf"
    parser.add_argument(
        "--source",
        type=Path,
        default=default_source,
        help=f"Local PDF path (default: {default_source})",
    )
    parser.add_argument(
        "--filename",
        default="ratecon_1000324868.pdf",
        help="Object name under the folder (default: ratecon_1000324868.pdf)",
    )
    parser.add_argument(
        "--folder",
        default="pod_attachments",
        help="Bucket subfolder under freightx/ (default: pod_attachments)",
    )
    args = parser.parse_args()

    src = args.source.resolve()
    if not src.is_file():
        print(f"[upload_ratecon_to_s3] ERROR: source file not found: {src}", file=sys.stderr)
        return 1

    data = src.read_bytes()
    print(f"[upload_ratecon_to_s3] read {len(data)} bytes from {src}")

    result = bucket.upload_file(
        file_content=data,
        filename=args.filename,
        content_type="application/pdf",
        folder=args.folder,
    )

    if result["success"]:
        print(f"[upload_ratecon_to_s3] OK object_key={result['object_key']}")
        return 0

    print(f"[upload_ratecon_to_s3] FAILED: {result.get('error_message')}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
