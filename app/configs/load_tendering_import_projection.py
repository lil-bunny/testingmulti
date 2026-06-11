"""Column projection presets for load tendering excel imports (logical key -> header aliases).

Gelita Ship Schedule (SAP export) — column letters for reference:
- B (ANR): order / pickup #
- E (LIEFAN): delivery address code (join to delivery_location.xlsx column C)
- P (LIEDAT): ship date
- Q (MEBEST): order quantity
- S (VKPREIS): cost per unit (total value ≈ S × Q)
- T (EINTREFFDAT): delivery date
- V (ARTSPEZ): pack code
- AM (ME): unit of measure for order quantity
- AS (BESTTXT): customer PO / reference
- BE (STATUSTEXT): line status (some codes mean do not ship; see row 10 in file)
"""

from __future__ import annotations

from typing import Final

LOAD_TENDERING_ROW_PROJECTION: Final[dict[str, tuple[str, ...]]] = {
    # Not used for tenders.customer_name (see delivery_location.xlsx column J).
    "customer_match": ("Customer Match", "KDMATCH"),
    "product_name": ("Product name", "Product Name", "TEXT1"),
    "order_quantity": ("Order quantity", "Order Quantity", "MEBEST"),
    "shipping_date": (
        "Ship date",
        "Ship Date",
        "shipping date",
        "Shipping Date",
        "LIEDAT",
    ),
    "delivery_date": ("delivery date", "Delivery Date", "EINTREFFDAT"),
    "order_number": ("Order #", "Order Number", "ANR"),
    "order_position": ("Order position", "Order Position", "order position", "POSIT"),
    "pack_code": ("Pack code", "pack_code", "Pack Code", "ARTSPEZ"),
    "delivery_address_code": ("LIEFAN", "Liefan"),
    "po_number": ("BESTTXT",),
    "price_per_unit": ("VKPREIS",),
    "weight_unit": ("ME", "Unit of measure", "unit of measure"),
}
