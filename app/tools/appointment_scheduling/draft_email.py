"""Build HITL email draft HTML (templates in code)."""

from __future__ import annotations

import re
from typing import Any

from app.domain.appointment_scheduling.costco import is_costco_customer
from app.domain.appointment_scheduling.models import (
    DraftStatic,
    EmailDraft,
    LlmSchedulingDecision,
    PickupDropoffData,
    SchedulingPayload,
)

_DEFAULT_COMMODITY = "DIAMOND PET FOODS"
_DEL_APPT_REQ_TOKEN_RE = re.compile(r'DEL APPT REQ\s+"([^"]+)"', re.IGNORECASE)


def is_del_appt_req_subject(subject: Any) -> bool:
    """True when subject contains the appointment scheduling DEL APPT REQ marker."""
    return "del appt req" in str(subject or "").lower()


def parse_del_appt_req_subject_token(subject: Any) -> str | None:
    """Extract quoted load id or reference number from a DEL APPT REQ subject."""
    text = str(subject or "").strip()
    if not text:
        return None
    match = _DEL_APPT_REQ_TOKEN_RE.search(text)
    if not match:
        return None
    token = match.group(1).strip()
    return token if token else None


def _e(value: Any) -> str:
    return "" if value is None else str(value)


def _n(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None


def build_draft_static_from_turvo(
    *,
    turvo_shipment: dict[str, Any],
    reference_number: str,
    shipment_details: str,
    commodity: str | None = None,
    footer_name: str = "T3RA Logistics Team",
    footer_email: str = "mikey@t3ralogistics.com",
    footer_phone: str = "(916) 458-5833",
    footer_title: str = "",
) -> DraftStatic:
    email_name, domain_name = "mikey", "t3ralogistics.com"
    if footer_email and "@" in footer_email:
        email_name, domain_name = footer_email.split("@", 1)
    return DraftStatic(
        reference_number=reference_number,
        shipment_details=shipment_details,
        name=footer_name,
        description=footer_title,
        email_name=email_name,
        email=footer_email,
        domain_name=domain_name,
        phone=footer_phone,
        commodity=commodity or _DEFAULT_COMMODITY,
    )


def build_shipment_details_summary(
    *,
    reference_number: str,
    pickup_dropoff: dict[str, Any],
) -> str:
    pickup = pickup_dropoff.get("pickup_data") or {}
    dropoff = pickup_dropoff.get("dropoff_data") or {}
    parts = [
        f"Ref: {reference_number}",
        f"Pickup: {pickup.get('location', '')} ({pickup.get('date', '')})",
        f"Dropoff: {dropoff.get('location', '')}",
    ]
    return " | ".join(p for p in parts if p.strip())


def build_email_draft(
    *,
    pickup_dropoff: PickupDropoffData | dict[str, Any],
    llm_decision: LlmSchedulingDecision | dict[str, Any],
    draft_static: DraftStatic | dict[str, Any],
    to_email: str,
    cc: list[str] | str,
    load_id: str,
    customer_name: str,
) -> tuple[EmailDraft, SchedulingPayload]:
    pickup = pickup_dropoff if isinstance(pickup_dropoff, dict) else pickup_dropoff.model_dump()
    llm = llm_decision if isinstance(llm_decision, dict) else llm_decision.model_dump()
    static = draft_static if isinstance(draft_static, dict) else draft_static.model_dump()

    weekday = _e(llm.get("calculated_delivery_weekday"))
    date = _e(llm.get("calculated_delivery_date"))
    po = _e(pickup.get("po_number"))
    pallet_count = _n(pickup.get("pallet_count"))
    pallet_str = str(pallet_count) if pallet_count is not None else ""
    commodity = _e(static.get("commodity"))
    reference_number = _e(static.get("reference_number"))
    shipment_details = _e(static.get("shipment_details"))

    cc_list = cc if isinstance(cc, list) else [c.strip() for c in _e(cc).split(",") if c.strip()]
    costco = is_costco_customer(customer_name)

    if costco:
        subject = f'DEL APPT REQ "{reference_number}"'
    else:
        subject = f'DEL APPT REQ "{_e(load_id)}"'

    if costco:
        date_with_time = (date + " 06:00") if date else "06:00"
        content_html = (
            '<p style="margin:0 0 20px;font-size:15px;color:#374151;">Hi,</p>'
            '<p style="margin:0 0 24px;font-size:15px;color:#374151;">Please set the delivery for '
            f'<strong style="color:#111827;">{weekday}</strong>'
            f' on <strong style="color:#111827;">{date_with_time}</strong>.</p>'
        )
    else:
        content_html = (
            '<p style="margin:0 0 20px;font-size:15px;color:#374151;">Hi,</p>'
            '<p style="margin:0 0 24px;font-size:15px;color:#374151;">Please set the delivery for '
            f'<strong style="color:#111827;">{weekday}</strong>'
            f' on <strong style="color:#111827;">{date}</strong>.</p>'
            '<table role="presentation" cellspacing="0" cellpadding="0" '
            'style="width:100%;border-collapse:collapse;font-size:14px;">'
            "<tr>"
            '<td style="padding:8px 0;border-bottom:1px solid #e5e7eb;color:#6b7280;">PO#</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid #e5e7eb;text-align:right;font-weight:500;color:#374151;">{po}</td>'
            "</tr>"
            "<tr>"
            '<td style="padding:8px 0;border-bottom:1px solid #e5e7eb;color:#6b7280;">Pallets</td>'
            f'<td style="padding:8px 0;border-bottom:1px solid #e5e7eb;text-align:right;font-weight:500;color:#374151;">{pallet_str}</td>'
            "</tr>"
            "<tr>"
            '<td style="padding:8px 0;color:#6b7280;">Commodity</td>'
            f'<td style="padding:8px 0;text-align:right;font-weight:500;color:#374151;">{commodity}</td>'
            "</tr>"
            "</table>"
        )

    footer_html = (
        '<p style="margin:0 0 4px;font-size:15px;color:#374151;">Best Regards,</p>'
        f'<p style="margin:0 0 16px;font-size:15px;font-weight:600;color:#374151;">{_e(static.get("name"))}</p>'
        f'<p style="margin:0 0 6px;font-size:14px;color:#374151;">{_e(static.get("email"))}</p>'
        f'<p style="margin:0;font-size:14px;color:#374151;">{_e(static.get("phone"))}</p>'
    )

    full_html = (
        "<!DOCTYPE html><html><head>"
        '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<meta http-equiv="X-UA-Compatible" content="IE=edge">'
        "</head>"
        '<body style="margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,Helvetica Neue,Arial,sans-serif;font-size:15px;line-height:1.5;color:#374151;background:#ffffff;">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0">'
        "<tr><td>"
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;background:#ffffff;">'
        '<tr><td style="padding:28px 0 24px;">'
        f"{content_html}"
        "</td></tr>"
        '<tr><td style="padding:0 0 28px;">'
        f"{footer_html}"
        "</td></tr>"
        "</table>"
        "</td></tr>"
        "</table>"
        "</body></html>"
    )

    email_draft = EmailDraft(
        to=_e(to_email),
        cc=cc_list,
        subject=subject,
        full_html=full_html,
    )
    scheduling_payload = SchedulingPayload(
        reference_number=reference_number,
        shipment_details=shipment_details,
        proposed_pickup_at=_e(llm.get("pcs_pickup_date") or llm.get("selected_pickup_date")) or None,
        proposed_delivery_at=date or None,
    )
    return email_draft, scheduling_payload
