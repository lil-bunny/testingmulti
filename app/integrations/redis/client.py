"""Per-process redis-py client for lifecycle run-queue keyspace."""

from __future__ import annotations

from redis import Redis

from app.core.config import settings

_client: Redis | None = None


def get_redis_client() -> Redis:
    """
    Return a process-local Redis client from ``CELERY_BROKER_URL``.

    Prefork workers each create their own client on first use.
    """
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.CELERY_BROKER_URL,
            decode_responses=True,
        )
    return _client
