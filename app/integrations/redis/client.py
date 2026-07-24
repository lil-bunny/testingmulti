"""Per-process redis-py client for lifecycle run-queue keyspace."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from redis import Redis

from app.core.config import settings

_client: Redis | None = None

# Celery/kombu broker URLs often use OpenSSL-style names; redis-py 5+ only
# accepts the lowercase verify-mode strings (see SSLConnection.__init__).
_CELERY_SSL_CERT_REQS_TO_REDIS_PY: dict[str, str] = {
    "CERT_NONE": "none",
    "CERT_OPTIONAL": "optional",
    "CERT_REQUIRED": "required",
}


def normalize_celery_broker_url_for_redis_py(url: str) -> str:
    """Map Celery ``ssl_cert_reqs=CERT_*`` query values to redis-py ``none|optional|required``."""
    parts = urlsplit(url)
    if not parts.query:
        return url

    pairs = parse_qsl(parts.query, keep_blank_values=True)
    changed = False
    normalized: list[tuple[str, str]] = []
    for key, value in pairs:
        if key == "ssl_cert_reqs" and value in _CELERY_SSL_CERT_REQS_TO_REDIS_PY:
            normalized.append((key, _CELERY_SSL_CERT_REQS_TO_REDIS_PY[value]))
            changed = True
        else:
            normalized.append((key, value))

    if not changed:
        return url

    return urlunsplit(
        (parts.scheme, parts.netloc, parts.path, urlencode(normalized), parts.fragment)
    )


def get_redis_client() -> Redis:
    """
    Return a process-local Redis client from ``CELERY_BROKER_URL``.

    Prefork workers each create their own client on first use.
    """
    global _client
    if _client is None:
        broker_url = normalize_celery_broker_url_for_redis_py(settings.CELERY_BROKER_URL)
        _client = Redis.from_url(
            broker_url,
            decode_responses=True,
        )
    return _client
