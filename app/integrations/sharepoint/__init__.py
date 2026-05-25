"""SharePoint integration: download files shared via anonymous links.

Public surface:
    * :func:`fetch_sharepoint_xlsx_bytes` — fetch an ``.xlsx`` shared via an
      anonymous share URL and return its raw bytes.
    * :class:`SharePointDownloadError` — raised on any failure (HTTP error,
      non-xlsx body, etc.) so callers can branch on a single typed error.
"""

from app.integrations.sharepoint.excel_reader import (
    SharePointDownloadError,
    fetch_sharepoint_xlsx_bytes,
)

__all__ = ["SharePointDownloadError", "fetch_sharepoint_xlsx_bytes"]
