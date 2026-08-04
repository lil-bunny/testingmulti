"""PoD-vs-Turvo scoring points, field labels, and remark / exception copy.

Score model:

- signature: identity field inside delivery stop (0/60)
- reference_id per stop (pickup / delivery): up to 20 each, prorated by the
  ratio of matched Turvo POs on that stop
- shipment_detail fields (dates + pickup/delivery location and address) are
  always scored with source/target values
- the final score aggregation (proration) is computed by freightx-api at
  read time, not stored
"""

from __future__ import annotations

# Score-bearing point values
SIGNATURE_POINTS = 60
REFERENCE_ID_POINTS_PER_STOP = 20

# Diff point values
DATE_POINTS = 10
TEXT_POINTS = 5

# Stop types
STOP_TYPE_PICKUP = "pickup"
STOP_TYPE_DELIVERY = "delivery"

# Field labels
LABEL_SIGNATURE = "signature"
LABEL_REFERENCE_ID = "reference_id"

# Top-level remarks / review reasons
REMARK_NO_TURVO_PO = "No Turvo PO found for this shipment; cannot score."

# Signature remarks
REMARK_SIGNATURE_ABSENT = "No proof of delivery found on the document"
REMARK_SIGNATURE_PRESENT = "Proof of delivery confirmed"

# Reference-id remarks (templates)
REMARK_REFERENCE_ID_MATCH_TEMPLATE = (
    "{matched} of {total} {stop_type} PO numbers matched"
)
REMARK_REFERENCE_ID_NO_MATCH_TEMPLATE = (
    "None of the {stop_type} PO numbers matched"
)
REMARK_REFERENCE_ID_NO_POS_TEMPLATE = (
    "No PO numbers configured for {stop_type}"
)

# Diff remarks (templates)
# {display_label} is injected by the scorer as a human-friendly name (e.g. "Pickup date")
REMARK_DATE_MATCH_TEMPLATE = "{display_label} matches"
REMARK_DATE_MISMATCH_TEMPLATE = "{display_label} does not match"
REMARK_DATE_MISSING_TEMPLATE = "{display_label} not found on POD"
REMARK_TEXT_MISSING_TEMPLATE = "{display_label} not found on POD"
REMARK_TEXT_IDENTIFIABLE_TEMPLATE = "{display_label} found on POD"
REMARK_TEXT_NO_MATCH_TEMPLATE = (
    "{display_label} does not match"
)

# Human-friendly display labels for field keys
FIELD_DISPLAY_LABELS: dict[str, str] = {
    "pickup_date": "Pickup date",
    "delivery_date": "Delivery date",
    "pickup_location": "Pickup location",
    "pickup_address": "Pickup address",
    "delivery_location": "Delivery location",
    "delivery_address": "Delivery address",
}

# Exception details
EXCEPTION_DAMAGE_DEFAULT_DETAIL = "Damage detected on POD."
EXCEPTION_PALLET_QTY_TEMPLATE = "Expected {ordered_qty} pallets, received {pallets_shipped}."
