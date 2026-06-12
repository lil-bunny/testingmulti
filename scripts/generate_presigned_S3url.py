"""
Generate a presigned HTTPS GET URL for a private S3 object.

Uses ``S3Bucket.generate_presigned_S3url`` with the same credentials/config
used by the application.

Examples:
    uv run python scripts/generate_presigned_S3url.py

    uv run python scripts/generate_presigned_S3url.py \
        ratecon_attachments/ratecon_1000315335.pdf

    uv run python scripts/generate_presigned_S3url.py \
        ratecon_attachments/ratecon_1000315335.pdf \
        --expires 900

    uv run python scripts/generate_presigned_S3url.py \
        --json \
        ratecon_attachments/ratecon_1000315335.pdf

Requirements:
    - `.env` at repo root with BUCKET_* settings
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / ".env", override=False)

from app.services.s3bucket_service import bucket  # noqa: E402

DEFAULT_OBJECT_KEY = "pod_attachments/pod_1000324868.pdf"
# DEFAULT_OBJECT_KEY = "ratecon_attachments/ratecon_1000315335.pdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a presigned S3 GetObject URL."
    )

    parser.add_argument(
        "object_key",
        nargs="?",
        default=DEFAULT_OBJECT_KEY,
        help=f"S3 object key (default: {DEFAULT_OBJECT_KEY})",
    )

    parser.add_argument(
        "--expires",
        type=int,
        default=None,
        help="TTL in seconds (defaults to BUCKET_PRESIGN_EXPIRES_SECONDS)",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full JSON response",
    )

    return parser.parse_args()


def main() -> int:
    args = parse_args()

    result = bucket.presign_get_object(
        args.object_key,
        expires_in=args.expires,
    )

    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result.get("success") else 1

    if not result.get("success"):
        print(
            f"[presign_get_object] FAILED: {result.get('error_message')}",
            file=sys.stderr,
        )
        return 1

    print(result["url"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())