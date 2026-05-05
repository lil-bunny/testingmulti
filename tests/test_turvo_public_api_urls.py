from app.integrations.turvo.public_api_urls import (
    build_oauth_token_url,
    normalize_turvo_publicapi_url,
)


def test_normalize_strips_trailing_slash():
    assert (
        normalize_turvo_publicapi_url("https://example.com/")
        == "https://example.com"
    )


def test_normalize_strips_api_v1_segment():
    assert (
        normalize_turvo_publicapi_url("https://host/api/v1/extra")
        == "https://host"
    )


def test_normalize_strips_trailing_v1():
    assert normalize_turvo_publicapi_url("https://host/v1") == "https://host"


def test_build_oauth_token_url_has_query():
    u = build_oauth_token_url("https://host", "cid", "csec")
    assert u.startswith("https://host/v1/oauth/token?")
    assert "client_id=cid" in u
    assert "client_secret=csec" in u
