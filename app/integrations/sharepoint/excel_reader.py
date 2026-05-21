"""Download an Excel file from a SharePoint anonymous share link.

SharePoint share URLs of the form ``.../personal/<user>/<token>`` serve the
Office Web viewer by default. Appending ``download=1`` to the query string
tells SharePoint to return the raw file bytes instead, which works without
authentication **as long as the share is set to "anyone with the link"**.

Pure ``urllib`` (and therefore ``pandas.read_excel(url)``) is rejected by
SharePoint with HTTP 403 because of its default User-Agent. We use ``httpx``
with an explicit User-Agent header and validate that the response really is
an ``.xlsx`` workbook before returning the bytes — if the share has been
revoked or rotated, SharePoint typically returns an HTML login page with a
200 status, and we want to fail loudly rather than hand HTML to ``pandas``.
"""

from __future__ import annotations

import httpx

from app.core.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_TIMEOUT_S = 60.0
_DEFAULT_USER_AGENT = "freightx-agents/sharepoint-reader"
_XLSX_CONTENT_TYPE_PREFIX = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml"
)
_XLSX_ZIP_MAGIC = b"PK"


class SharePointDownloadError(Exception):
    """Raised when a SharePoint share URL did not yield a usable ``.xlsx``."""


def _append_download_param(share_url: str) -> str:
    """Append ``download=1`` using ``?`` or ``&`` depending on existing query."""
    separator = "&" if "?" in share_url else "?"
    return f"{share_url}{separator}download=1"


def fetch_sharepoint_xlsx_bytes(
    share_url: str,
    *,
    timeout: float = _DEFAULT_TIMEOUT_S,
) -> bytes:
    """Fetch an ``.xlsx`` from a SharePoint anonymous share URL.

    Args:
        share_url: SharePoint share link (typically of the form
            ``https://<tenant>.sharepoint.com/:x:/g/personal/<user>/<token>``).
            Existing query parameters are preserved.
        timeout: Overall HTTP timeout in seconds.

    Returns:
        The raw bytes of the ``.xlsx`` workbook.

    Raises:
        SharePointDownloadError: If the request fails, the response is not
            ``2xx``, or the body is not a valid ``.xlsx`` workbook (e.g. an
            HTML login page was returned because the share is no longer
            anonymous).
    """
    if not share_url or not share_url.strip():
        raise SharePointDownloadError("share_url must be a non-empty string")

    download_url = _append_download_param(share_url.strip())

    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": _DEFAULT_USER_AGENT},
        ) as client:
            response = client.get(download_url)
    except httpx.HTTPError as exc:
        logger.exception("SharePoint download HTTP error")
        raise SharePointDownloadError(
            f"SharePoint download failed: {type(exc).__name__}"
        ) from exc

    if response.status_code >= 400:
        logger.warning(
            "SharePoint download non-2xx status=%s len=%s",
            response.status_code,
            len(response.content),
        )
        raise SharePointDownloadError(
            f"SharePoint returned HTTP {response.status_code}"
        )

    content = response.content or b""
    content_type = (response.headers.get("Content-Type") or "").lower()

    if not content.startswith(_XLSX_ZIP_MAGIC):
        logger.warning(
            "SharePoint download is not an xlsx: status=%s content_type=%s "
            "len=%s. Share link may have been revoked or rotated.",
            response.status_code,
            content_type,
            len(content),
        )
        raise SharePointDownloadError(
            "SharePoint response is not an .xlsx workbook "
            "(missing PK zip header). The share link may have been revoked, "
            "rotated, or changed to require sign-in."
        )

    if content_type and not content_type.startswith(_XLSX_CONTENT_TYPE_PREFIX):
        logger.warning(
            "SharePoint download unexpected Content-Type=%s (continuing because "
            "PK header is present, but verify the source)",
            content_type,
        )

    logger.info(
        "SharePoint download ok bytes=%s content_type=%s",
        len(content),
        content_type,
    )
    return content
