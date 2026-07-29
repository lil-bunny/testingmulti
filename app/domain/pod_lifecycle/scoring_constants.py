"""PoD-vs-Turvo scoring points, field labels, and remark / exception copy."""

from __future__ import annotations

# Pass 1 point values
PASS1_SIGNATURE_POINTS = 60
PASS1_REFERENCE_ID_POINTS = 40

# Pass 2 point values
PASS2_DATE_POINTS = 10
PASS2_TEXT_POINTS = 5

# Field labels
LABEL_SIGNATURE = "signature"
LABEL_REFERENCE_ID = "reference_id"

# Top-level remarks / review reasons
REMARK_PICKUP_SIGNATURE_MISSING = "Pickup signature not present."
REMARK_NO_TURVO_PO = "No Turvo PO found for this shipment; cannot score."

# Pass 1 signature remarks
REMARK_SIGNATURE_ABSENT = (
    "No receiver signature, delivery stamp, or delivery sticker detected."
)
REMARK_SIGNATURE_PRESENT = (
    "Receiver signature, delivery stamp, or delivery sticker present."
)
REMARK_REFERENCE_ID_SKIPPED_SIGNATURE_FAILED = (
    "Not evaluated: Pass 1 signature check failed."
)

# Pass 1 reference-id remarks (templates)
REMARK_REFERENCE_ID_MATCH_TEMPLATE = (
    "POD reference number and expected Turvo stop match for PO {po_number}."
)
REMARK_REFERENCE_ID_NO_MATCH_TEMPLATE = (
    "No POD PO + expected-stop match for Turvo PO {po_number}; running Pass 2."
)

# Pass 2 date remarks (templates)
REMARK_DATE_MATCH_TEMPLATE = "{label} matches Turvo ({turvo_date})."
REMARK_DATE_NO_MATCH_TEMPLATE = "{label} does not match Turvo or is missing on POD."

# Pass 2 text remarks (templates)
REMARK_TEXT_MISSING_TEMPLATE = "{label} missing or blank on POD."
REMARK_TEXT_IDENTIFIABLE_TEMPLATE = (
    "{label} present and identifiable on POD: '{pod_text}'."
)
REMARK_TEXT_NO_MATCH_TEMPLATE = (
    "{label} on POD ('{pod_text}') does not match Turvo ('{turvo_value}')."
)

# Exception details
EXCEPTION_DAMAGE_DEFAULT_DETAIL = "Damage detected on POD."
EXCEPTION_PALLET_QTY_TEMPLATE = "Expected {ordered_qty} pallets, received {pallets_shipped}."
