"""
Static defaults for Gelita load tendering.

Runtime may overlay values from DB `tenants.settings`; these are the in-repo fallbacks.
"""

# Pallet / LTL–FTL (lbs and cutoff). Confirm `PALLET_WEIGHT_LBS` with product when known.
PALLET_WEIGHT_LBS: float = 45.0
PALLET_THRESHOLD: int = 8

VENDOR_EMAIL: str = "kansalayush28@gmail.com"
ANA_GELITA_AT_FREIGHTX_AI_ACCOUNT_ID: str = ""

REMINDER_BODY: str = "Following up on the request"
REMINDER_1_HOURS: float = 0
REMINDER_2_HOURS: float = 0.01666666
ESCALATION_HOURS: float = 0.03333332
# REMINDER_1_HOURS: float = 12
# REMINDER_2_HOURS: float = 24
# ESCALATION_HOURS: float = 28

# Escalation email (28h Celery path): sample ops recipient and copy — replace with real ops inboxes.
ESCALATION_NOTIFY_EMAIL: str = "kansalayush28+escalateGelita@gmail.com"
ESCALATION_EMAIL_SUBJECT: str = "Gelita tender escalation (order {order_number})"
ESCALATION_EMAIL_BODY: str = """escalation email.

Lifecycle ID: {workflow_lifecycle_id}
Tender ID: {tender_id}
Order number: {order_number}

This tender did not receive a carrier acknowledgment before the escalation window. Please review in the TMS or workflow tool.

---
Operational escalation routing and copy TBD.
"""

# Unipile account id for outbound mail (e.g. ana@gelita.com)
GELITA_SENDER_ACCOUNT_ID: str = "7jKV_5jBQVG8med4nvXHJw"

# Outbound tender email body (plain text; Unipile ``body``). Service layer replaces placeholders when sending.
EMAIL_TEMPLATE_HTML: str = """Please Provide Your BOL by 1300 CST day prior of shipment or GELITA will use their own. "Make sure to include your sales coordinator and the whole logistics team (Chris Alter, Taylor Hudson, & Tonya Jackson) when sending your BOL
Pickup address:
{pickup_address}

Deliver to:
{delivery_address}

Order #{order_number}
Customer PO #{customer_po}
Ship date: {ship_date}
Pieces: {pieces}
Number of pallets: {pallets}
Gross weight: ~{gross_weight}
Product: {product_name}
NMFC Code 73260-00 Class 70
Non-Stackable
Non-Hazardous
Loading hours 1300-1600 day of shipment.
"""
