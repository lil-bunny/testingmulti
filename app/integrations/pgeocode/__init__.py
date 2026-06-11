"""Pgeocode integration: resolve state and postal from country + location fields.

Public surface:
    * :func:`lookup_state` — postal → state
    * :func:`lookup_postal` — city + state → postal (fallback when zip missing)
"""

from app.integrations.pgeocode.state_lookup import lookup_postal, lookup_state

__all__ = ["lookup_postal", "lookup_state"]
