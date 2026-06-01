"""Column projection presets for load tendering excel imports (logical key -> header aliases)."""

from __future__ import annotations

from typing import Final

LOAD_TENDERING_ROW_PROJECTION: Final[dict[str, tuple[str, ...]]] = {
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
    "delivery_address_code": ("Delivery address", "LIEFAN"),
    "po_number": ("BESTTXT",),
    "price_per_unit": ("VKPREIS",),
}
