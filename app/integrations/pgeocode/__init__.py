"""Pgeocode integration: resolve state names from country + postal code.

Public surface:
    * :func:`lookup_state` — given a sheet country name and postal code,
      return GeoNames ``state_code`` (preferred) or ``state_name``, or ``None``.
"""

from app.integrations.pgeocode.state_lookup import lookup_state

__all__ = ["lookup_state"]
