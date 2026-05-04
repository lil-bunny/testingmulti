"""Build Turvo Public API OAuth token URL from configured base."""


def normalize_turvo_publicapi_url(raw: str) -> str:
    """
    Strip trailing slashes; if path contains /api/v1, keep the part before it;
    if the path ends with /v1, strip that segment.
    """
    s = raw.strip().rstrip("/")
    if "/api/v1" in s:
        s = s.split("/api/v1", 1)[0].rstrip("/")
    if s.endswith("/v1"):
        s = s[:-3].rstrip("/")
    return s


def build_oauth_token_url(
    normalized_base: str, client_id: str, client_secret: str
) -> str:
    from urllib.parse import urlencode, quote

    path = f"{normalized_base.rstrip('/')}/v1/oauth/token"
    q = urlencode(
        {"client_id": client_id, "client_secret": client_secret},
        quote_via=quote,
    )
    return f"{path}?{q}"


def build_publicapi_v1_url(normalized_base: str, path: str) -> str:
    """Compose absolute Turvo Public API v1 URL from a normalized base and a relative path."""
    base = normalized_base.rstrip("/")
    suffix = path if path.startswith("/") else f"/{path}"
    return f"{base}/v1{suffix}"
