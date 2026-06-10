"""Test helpers for API auth."""

from __future__ import annotations

from app.domain.api_user import ApiUser

_TEST_USER_ID = "11111111-1111-1111-1111-111111111111"
_TEST_TENANT_ID = "22222222-2222-2222-2222-222222222222"


def test_user_id() -> str:
    return _TEST_USER_ID


def test_tenant_id() -> str:
    return _TEST_TENANT_ID


def make_test_api_user(
    *,
    permissions: list[str] | None = None,
    tenant_id: str | None = _TEST_TENANT_ID,
    email: str = "test@example.com",
    name: str = "Test User",
    user_id: str = _TEST_USER_ID,
) -> ApiUser:
    return ApiUser(
        id=user_id,
        name=name,
        email=email,
        tenant_id=tenant_id,
        tenant_ids=[tenant_id] if tenant_id else [],
        permissions=permissions or [],
    )


def bearer_headers(token: str = "test-access-token") -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}
