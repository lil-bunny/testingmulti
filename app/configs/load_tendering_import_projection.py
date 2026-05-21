"""Column projection presets for load tendering excel imports (logical key -> header aliases)."""

from __future__ import annotations

from typing import Final

LOAD_TENDERING_ROW_PROJECTION: Final[dict[str, tuple[str, ...]]] = {
    "customer_match": ("Customer Match",),
    "product_name": ("Product name", "Product Name"),
    "order_quantity": ("Order quantity", "Order Quantity"),
    "shipping_date": ("Ship date", "Ship Date", "shipping date", "Shipping Date"),
    "delivery_date": ("delivery date", "Delivery Date"),
    "order_number": ("Order #", "Order Number"),
    "pack_code": ("Pack code", "pack_code", "Pack Code"),
    "delivery_address_code": ("Delivery address",),
    "po_number": ("BESTTXT",),
}
