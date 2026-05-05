"""
Exercise ``upload_ratecon_email_attachments_to_s3`` end-to-end:

1. Fetch each attachment via Unipile (``get_email_attachments``).
2. Upload bytes to S3 under ``freightx/pod_attachments/ratecon_<shipment>.<ext>``.

Requires the same .env as the app:
- Unipile creds (for fetch)
- ``BUCKET_*`` (for S3)

**S3 / PermanentRedirect:** By default this script clears ``BUCKET_ENDPOINT`` for the
process before importing the app, so boto3 uses standard AWS regional routing with
``BUCKET_REGION`` (avoids "must be addressed using the specified endpoint" when
``.env`` points at a generic ``s3.<region>.amazonaws.com`` URL). For DigitalOcean
Spaces or a custom S3-compatible host, pass ``--use-env-bucket-endpoint``.

Usage (from repo root):

  uv run python scripts/test_ratecon_attachment_upload.py \\
    --email-id YPNSu5tsW32vaasFc4Rv_Q \\
    --attachment-id att1 \\
    --shipment-id 56368 \\
    --account-id FqA0zzsTQJ-5naFro793wQ

Multiple attachments (same email):

  uv run python scripts/test_ratecon_attachment_upload.py \\
    --email-id EMAIL_ID --shipment-id SHIP_ID \\
    --attachment-id A1 --attachment-id A2 \\
    --account-id ACCOUNT_ID_OR_OMIT

Optional attachment display name:

  uv run python scripts/test_ratecon_attachment_upload.py ... --attachment-name ratecon.pdf
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _ensure_aws_default_s3_endpoint(*, use_env_bucket_endpoint: bool) -> None:
    """Unset BUCKET_ENDPOINT unless user wants .env verbatim (Spaces / custom URL)."""
    if use_env_bucket_endpoint:
        return
    os.environ["BUCKET_ENDPOINT"] = ""


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test ratecon email attachment fetch + S3 upload (Unipile + bucket).",
    )
    parser.add_argument(
        "--use-env-bucket-endpoint",
        action="store_true",
        help="Keep BUCKET_ENDPOINT from .env (DigitalOcean Spaces, custom S3 host). "
        "Default: clear it for AWS so routing follows BUCKET_REGION only.",
    )
    parser.add_argument(
        "--email-id",
        required=True,
        help="Unipile email/message id",
    )
    parser.add_argument(
        "--attachment-id",
        action="append",
        dest="attachment_ids",
        metavar="ID",
        help="Unipile attachment id (repeat for multiple attachments)",
    )
    parser.add_argument(
        "--attachments-json",
        type=Path,
        help="Optional JSON path: list of objects with at least 'id'; "
        'e.g. [{"id":"A1","name":"ratecon.pdf"}]',
    )
    parser.add_argument(
        "--shipment-id",
        default="",
        help="Shipment / load token for object basename (empty -> 'unknown')",
    )
    parser.add_argument(
        "--account-id",
        default="",
        help="Unipile account id (omit or empty for None)",
    )
    parser.add_argument(
        "--attachment-name",
        default="",
        help="Optional 'name' field on each synthetic attachment row (metadata only)",
    )
    args = parser.parse_args()

    _ensure_aws_default_s3_endpoint(use_env_bucket_endpoint=args.use_env_bucket_endpoint)
    if not args.use_env_bucket_endpoint:
        print(
            "[test_ratecon_attachment_upload] BUCKET_ENDPOINT cleared for this run "
            "(use --use-env-bucket-endpoint to keep .env value).",
            file=sys.stderr,
        )

    from app.services.attachment_normalizer import ratecon_shipment_object_basename  # noqa: E402
    from app.tools.ratecon import upload_ratecon_email_attachments_to_s3  # noqa: E402

    attachments: list[dict]
    if args.attachments_json is not None:
        p = args.attachments_json.resolve()
        if not p.is_file():
            print(f"[test_ratecon_attachment_upload] ERROR: file not found: {p}", file=sys.stderr)
            return 1
        raw = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            print(
                "[test_ratecon_attachment_upload] ERROR: JSON must be a list of attachment objects",
                file=sys.stderr,
            )
            return 1
        attachments = [x for x in raw if isinstance(x, dict)]
    elif args.attachment_ids:
        name = (args.attachment_name or "").strip() or None
        attachments = [
            {"id": aid, **({"name": name} if name else {})} for aid in args.attachment_ids
        ]
    else:
        print(
            "[test_ratecon_attachment_upload] ERROR: provide --attachment-id (repeatable) "
            "or --attachments-json",
            file=sys.stderr,
        )
        return 1

    sid = args.shipment_id.strip()
    account = args.account_id.strip() or None
    basename = ratecon_shipment_object_basename(sid or "unknown")

    print(
        "[test_ratecon_attachment_upload] "
        f"email_id={args.email_id!r} attachment_count={len(attachments)} "
        f"shipment_id={sid or 'unknown'} object_basename={basename!r} account_id={account!r}"
    )

    out = upload_ratecon_email_attachments_to_s3(
        email_id=str(args.email_id).strip(),
        account_id=account,
        attachments=attachments,
        shipment_id=sid or "unknown",
    )

    print(json.dumps(out, indent=2))
    return 0 if out.get("all_succeeded") else 2


if __name__ == "__main__":
    raise SystemExit(main())
