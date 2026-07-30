"""Unit tests for redis-py broker URL normalization (Celery CERT_* → redis-py)."""

from __future__ import annotations

from redis import Redis

from app.integrations.redis.client import normalize_celery_broker_url_for_redis_py


def test_normalize_cert_none_to_none() -> None:
    url = "rediss://:secret@elasticache.example:6379/0?ssl_cert_reqs=CERT_NONE"
    assert (
        normalize_celery_broker_url_for_redis_py(url)
        == "rediss://:secret@elasticache.example:6379/0?ssl_cert_reqs=none"
    )


def test_normalize_leaves_redis_py_none_unchanged() -> None:
    url = "rediss://:secret@elasticache.example:6379/0?ssl_cert_reqs=none"
    assert normalize_celery_broker_url_for_redis_py(url) == url


def test_normalize_leaves_non_tls_url_unchanged() -> None:
    url = "redis://:secret@localhost:6379/0"
    assert normalize_celery_broker_url_for_redis_py(url) == url


def test_normalize_preserves_other_query_params() -> None:
    url = (
        "rediss://:secret@elasticache.example:6379/1"
        "?ssl_cert_reqs=CERT_REQUIRED&health_check_interval=30"
    )
    assert (
        normalize_celery_broker_url_for_redis_py(url)
        == "rediss://:secret@elasticache.example:6379/1"
        "?ssl_cert_reqs=required&health_check_interval=30"
    )


def test_normalized_cert_none_url_builds_ssl_connection() -> None:
    """Regression: redis-py 8 rejects ssl_cert_reqs=CERT_NONE at connection init."""
    raw = "rediss://:secret@127.0.0.1:6379/0?ssl_cert_reqs=CERT_NONE"
    normalized = normalize_celery_broker_url_for_redis_py(raw)
    conn = Redis.from_url(normalized, decode_responses=True).connection_pool.make_connection()
    assert conn.cert_reqs == 0  # ssl.CERT_NONE
