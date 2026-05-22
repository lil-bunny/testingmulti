"""
Static defaults for Gelita load tendering.

Runtime may overlay values from DB `tenants.settings`; these are the in-repo fallbacks.
"""

# Pallet / LTL–FTL (lbs and cutoff). Confirm `PALLET_WEIGHT_LBS` with product when known.
PALLET_WEIGHT_LBS: float = 45.0
PALLET_THRESHOLD: int = 8

VENDOR_EMAIL: str = "kansalayush28+fx@gmail.com"
ANA_GELITA_AT_FREIGHTX_AI_ACCOUNT_ID: str = "8Lu6Ht9vTyyN1Zdb1mVtPw"

REMINDER_BODY: str = "Following up on the request"
REMINDER_1_HOURS: float = 0.0166666667
REMINDER_2_HOURS: float = 0.05
ESCALATION_HOURS: float = 0.1
# REMINDER_1_HOURS: float = 12
# REMINDER_2_HOURS: float = 24
# ESCALATION_HOURS: float = 28

# Escalation email (28h Celery path): sample ops recipient and copy — replace with real ops inboxes.
ESCALATION_NOTIFY_EMAIL: str = "kansalayush28+escalateGelita@gmail.com"
ESCALATION_EMAIL_SUBJECT: str = "Gelita tender escalation (order {order_number})"
ESCALATION_EMAIL_BODY: str = """This tender did not receive a carrier acknowledgment before the escalation window. Please review this load: 

Lifecycle ID: {workflow_lifecycle_id}
Tender ID: {tender_id}
Order number: {order_number}
"""

# Unipile account id for outbound mail (e.g. ana@gelita.com)
ANA_AT_GELITA_ACCOUNT_ID: str = "8Lu6Ht9vTyyN1Zdb1mVtPw"

# Fixed Gelita ship-from (USPS mailing block built via ``format_usps_mailing_address``).
GELITA_PICKUP_ADDRESS: dict[str, str | None] = {
    "city": "SERGEANT BLUFF",
    "name": "GELITA USA",
    "name2": None,
    "state": "Iowa",
    "country": "U.S.A.",
    "address1": "2445 PORT NEAL INDUSTRIAL RD",
    "address2": None,
    "postal_code": "51054",
}

# Outbound tender email body (HTML; Unipile ``body``). Placeholders filled in ``build_gelita_tender_email``.
EMAIL_TEMPLATE_HTML: str = """<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /><title>BOL Request Template</title></head>
<body style="font-family: Arial, Helvetica, sans-serif; font-size: 14px; line-height: 1.5; color: #111;">
<p style="margin-bottom: 4px;"><span style="background-color: #fff176; font-weight: bold; padding: 2px 4px;">Please Provide Your BOL by 1300 CST day prior of shipment or GELITA will use their own.</span> <span style="color: #555;">"Make sure to include your sales coordinator and the whole logistics team (Chris Alter, Taylor Hudson, &amp; Tonya Jackson) when sending your BOL"</span></p>
<br />
<p style="margin-bottom: 18px;"><strong>Pickup address:</strong><br />{pickup_address}</p>
<p style="margin-bottom: 18px;"><strong>Deliver to:</strong><br />{delivery_address}</p>
<p style="margin-bottom: 0;">Order #{order_number}<br />Customer PO #{customer_po}<br />Ship date: {ship_date}</p>
<br />
<p style="margin-top: 0;">Pieces: {pieces}<br />Number of pallets: {pallets}<br />Gross weight: ~{gross_weight}<br />Product: {product_name}<br />NMFC Code 73260-00 Class 70<br />Non-Stackable<br />Non-Hazardous</p>
<br />
<p><strong>Loading hours 1300-1600 day of shipment.</strong></p>
</body>
</html>"""

# Carrier reply classification (ack_received graph path). User message is plain reply text only.
CARRIER_ACK_SYSTEM_PROMPT: str = """You classify carrier email replies to a load tender request.

Return JSON only:
{"decision": string, "confidence": number, "reason": string}

decision must be exactly one of:
- "accepted" — the carrier clearly accepts or commits to the load tender (e.g. we accept, confirmed, will pick up, yes we can cover this load).
- "rejected" — clearly declines, cannot cover, passes, or refuses the tender.
- "do_nothing" — use for: questions only; unrelated content; out-of-office; ambiguous; attachment-only without accept/decline; shipper/tenant meta-replies in the thread (e.g. "thanks for the reply", "thank you", replying to someone else's acknowledgment); short conversational "acknowledged" or "got it" that only confirms seeing a prior message rather than accepting the tender; acknowledging a reminder/follow-up ("following up") without accepting the load.

Only use "accepted" when the message is a carrier business commitment to the tender, not polite thread chatter.

confidence is 0.0 to 1.0. reason is one short sentence."""
