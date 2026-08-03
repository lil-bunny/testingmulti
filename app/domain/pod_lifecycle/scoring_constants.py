"""PoD-vs-Turvo scoring points, field labels, and remark / exception copy.

Score model:

- signature: document-level delivery receiver proof, shared across POs (0/60)
- reference_id per stop (pickup / delivery): up to 20 each, prorated by the
  ratio of matched Turvo POs on that stop
- Pass 2 fields (dates + pickup/destination location and address) are always
  computed, scored, and stored with both Turvo and POD values (0/40 raw)
- the 40-point validation bucket combines reference_id + Pass 2 by proportional
  proration; the overall score is always out of 100
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
REMARK_SIGNATURE_ABSENT = (
    "No receiver signature, delivery stamp, or delivery sticker detected on the document."
)
REMARK_SIGNATURE_PRESENT = (
    "Receiver signature, delivery stamp, or delivery sticker present on the document."
)

# Reference-id remarks (templates)
REMARK_REFERENCE_ID_MATCH_TEMPLATE = (
    "POD POs match the Turvo {stop_type} stop ({matched} of {total} POs)."
)
REMARK_REFERENCE_ID_NO_MATCH_TEMPLATE = (
    "No POD PO matches the Turvo {stop_type} stop."
)
REMARK_REFERENCE_ID_NO_POS_TEMPLATE = (
    "No Turvo {stop_type} POs available; reference-id not scored."
)

# Diff remarks (templates)
REMARK_DATE_MATCH_TEMPLATE = "{label} matches Turvo ({turvo_date})."
REMARK_DATE_NO_MATCH_TEMPLATE = "{label} does not match Turvo or is missing on POD."
REMARK_TEXT_MISSING_TEMPLATE = "{label} missing or blank on POD."
REMARK_TEXT_IDENTIFIABLE_TEMPLATE = (
    "{label} present and identifiable on POD: '{pod_text}'."
)
REMARK_TEXT_NO_MATCH_TEMPLATE = (
    "{label} on POD ('{pod_text}') does not match Turvo ('{target}')."
)

# Exception details
EXCEPTION_DAMAGE_DEFAULT_DETAIL = "Damage detected on POD."
EXCEPTION_PALLET_QTY_TEMPLATE = "Expected {ordered_qty} pallets, received {pallets_shipped}."
