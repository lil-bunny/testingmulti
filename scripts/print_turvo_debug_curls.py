"""Print Turvo debug curl commands with live tokens from DB (local Postman use).

Loads tenant OAuth + TMS partner settings the same way ``TurvoApiClient`` does.
Output includes real bearer tokens — do not paste into shared channels.

Run from repo root::

    uv run python scripts/print_turvo_debug_curls.py
    uv run python scripts/print_turvo_debug_curls.py --mask
    uv run python scripts/print_turvo_debug_curls.py --name "Alyssa" --name "Alyssa Wolf"
    uv run python scripts/print_turvo_debug_curls.py --multiline --shell bash
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlencode

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

from app.integrations.turvo.public_api_urls import (
    build_oauth_token_url,
    build_publicapi_v1_url,
    build_turvo_ui_base_url,
    normalize_turvo_publicapi_url,
)
from app.services.turvo_oauth_service import TurvoOAuthService

DEFAULT_TENANT = "t3ra"
DEFAULT_CARRIER_ID = 848297
DEFAULT_NAMES = ("Alyssa", "Alyssa Wolf")
DEFAULT_CONTACT_IDS = (604186, 640680)


async def _resolve_auth(tenant_slug: str) -> tuple[str, str, str, dict[str, Any]]:
    oauth = TurvoOAuthService()
    tms = await asyncio.to_thread(oauth._load_tms, tenant_slug)
    tokens = await oauth.get_tenant_tokens(tenant_slug)
    if not tokens or not tokens.get("access_token"):
        raise SystemExit(
            f"No Turvo access token for tenant {tenant_slug!r}. "
            "Link Turvo via /api/user/turvo/authenticate first."
        )
    public_api_url = (tms.public_api_url or "").strip()
    if not public_api_url:
        raise SystemExit(f"Tenant {tenant_slug!r} missing tms.public_api_url")
    x_key = (tms.x_api_key or "").strip()
    if not x_key:
        raise SystemExit(f"Tenant {tenant_slug!r} missing tms.x_api_key")
    base = normalize_turvo_publicapi_url(public_api_url)
    meta = {
        "client_id": (tms.client_id or "publicapi").strip(),
        "client_secret": (tms.client_secret or "secret").strip(),
        "refresh_token": tokens.get("refresh_token"),
        "ui_base": build_turvo_ui_base_url(public_api_url),
    }
    return tokens["access_token"], x_key, base, meta


def _maybe_mask(value: str, *, mask: bool) -> str:
    if not mask or len(value) <= 12:
        return value
    return f"{value[:6]}...{value[-4:]}"


def _curl(
    *,
    method: str,
    url: str,
    headers: dict[str, str],
    body: str | None = None,
    shell: str,
    mask: bool,
    multiline: bool,
) -> str:
    hdrs: dict[str, str] = {}
    for k, v in headers.items():
        kl = k.lower()
        if mask and kl == "authorization" and v.lower().startswith("bearer "):
            hdrs[k] = f"Bearer {_maybe_mask(v[7:], mask=True)}"
        elif mask and kl == "x-api-key":
            hdrs[k] = _maybe_mask(v, mask=True)
        else:
            hdrs[k] = v

    exe = "curl.exe" if shell == "powershell" else "curl"
    quote_char = '"' if shell == "powershell" else "'"
    parts = [f"{exe} -sS -X {method.upper()} {quote_char}{url}{quote_char}"]
    for key, val in hdrs.items():
        parts.append(f'-H "{key}: {val}"')
    if body is not None:
        escaped = body.replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'--data "{escaped}"')

    if not multiline:
        return " ".join(parts)

    cont = "`" if shell == "powershell" else "\\"
    lines = [parts[0]]
    for part in parts[1:]:
        lines.append(f"  {cont}{part}")
    return "\n".join(lines)


def _public_api_headers(access_token: str, x_api_key: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "x-api-key": x_api_key,
    }


def _ui_headers(access_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
    }


def _contacts_list_url(base: str, name: str) -> str:
    params = urlencode(
        {"pageSize": "100", "start": "0", "name[eq]": name},
        quote_via=quote,
    )
    return build_publicapi_v1_url(base, f"/contacts/list?{params}")


def _print_section(title: str, curl: str) -> None:
    print(f"\n# --- {title} ---\n")
    print(curl)


async def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print Turvo API curl commands with tokens loaded from DB"
    )
    parser.add_argument("--tenant", default=DEFAULT_TENANT)
    parser.add_argument("--carrier-id", type=int, default=DEFAULT_CARRIER_ID)
    parser.add_argument(
        "--name",
        action="append",
        dest="names",
        help="Contact name for contacts/list name[eq] (repeatable)",
    )
    parser.add_argument(
        "--contact-id",
        action="append",
        type=int,
        dest="contact_ids",
        help="Contact id for GET /contacts/{id} (repeatable)",
    )
    parser.add_argument(
        "--shell",
        choices=("powershell", "bash"),
        default="powershell",
        help="curl binary style (default: curl.exe on Windows)",
    )
    parser.add_argument(
        "--multiline",
        action="store_true",
        help="Split curl across lines with shell continuations",
    )
    parser.add_argument(
        "--mask",
        action="store_true",
        help="Redact access token and x-api-key in output",
    )
    args = parser.parse_args()

    names = args.names if args.names else list(DEFAULT_NAMES)
    contact_ids = args.contact_ids if args.contact_ids else list(DEFAULT_CONTACT_IDS)

    access_token, x_api_key, base, meta = await _resolve_auth(args.tenant)
    pub_headers = _public_api_headers(access_token, x_api_key)
    ui_headers = _ui_headers(access_token)
    token_url = build_oauth_token_url(base, meta["client_id"], meta["client_secret"])

    print(f"# Turvo debug curls — tenant={args.tenant!r} one_line={not args.multiline}")
    print("# Tokens loaded from DB. Do not share this output.")

    if meta.get("refresh_token"):
        refresh_body = json.dumps(
            {"grant_type": "refresh_token", "refresh_token": meta["refresh_token"]},
            separators=(",", ":"),
        )
        if args.mask:
            refresh_body = json.dumps(
                {"grant_type": "refresh_token", "refresh_token": "***"},
                separators=(",", ":"),
            )
        _print_section(
            "OAuth refresh token (if access_token expires)",
            _curl(
                method="POST",
                url=token_url,
                headers={"Content-Type": "application/json", "x-api-key": x_api_key},
                body=refresh_body,
                shell=args.shell,
                mask=args.mask,
                multiline=args.multiline,
            ),
        )
    else:
        print("\n# No refresh_token in DB — use password grant manually if token expires.")

    curl_kw = {"shell": args.shell, "mask": args.mask, "multiline": args.multiline}

    for name in names:
        _print_section(
            f'contacts/list name[eq]={name!r}',
            _curl(
                method="GET",
                url=_contacts_list_url(base, name),
                headers=pub_headers,
                **curl_kw,
            ),
        )

    for contact_id in contact_ids:
        url = build_publicapi_v1_url(base, f"/contacts/{contact_id}?fullResponse=true")
        _print_section(
            f"GET contact {contact_id}",
            _curl(method="GET", url=url, headers=pub_headers, **curl_kw),
        )

    carrier_url = build_publicapi_v1_url(
        base, f"/carriers/{args.carrier_id}?fullResponse=true"
    )
    _print_section(
        f"GET carrier {args.carrier_id} (embed contacts)",
        _curl(method="GET", url=carrier_url, headers=pub_headers, **curl_kw),
    )

    ui_base = (meta.get("ui_base") or "").rstrip("/")
    if ui_base:
        ui_filter = json.dumps(
            {"contacts": {"start": 0, "pageSize": 200}, "criteria": []},
            separators=(",", ":"),
        )
        ui_params = urlencode(
            {"types": json.dumps(["contacts"]), "filter": ui_filter},
            quote_via=quote,
        )
        ui_url = f"{ui_base}/api/accounts/{args.carrier_id}?{ui_params}"
        _print_section(
            f"UI accounts contacts tab carrier {args.carrier_id} (phone search source)",
            _curl(method="GET", url=ui_url, headers=ui_headers, **curl_kw),
        )


if __name__ == "__main__":
    asyncio.run(main())
