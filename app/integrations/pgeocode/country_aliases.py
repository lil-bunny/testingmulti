"""Map free-text country names from the Gelita Delivery locations sheet to ISO2 codes.

``pgeocode.Nominatim`` requires a 2-letter ISO country code, but the delivery
locations sheet uses human-readable names with several non-standard variants
(e.g. ``"U.S.A."``, ``"Great Britain"``, ``"Pr of China"``, ``"Taiwan R.O.C."``).
This module owns the canonical mapping. Any sheet value not in the dict yields
``None``, which downstream is treated as "unable to resolve state" and falls
back to ``state: ""`` — never an exception.
"""

from __future__ import annotations

COUNTRY_TO_ISO: dict[str, str] = {
    "Argentina": "AR",
    "Australia": "AU",
    "Belgium": "BE",
    "Bolivia": "BO",
    "Brazil": "BR",
    "Canada": "CA",
    "Chile": "CL",
    "Colombia": "CO",
    "Costa Rica": "CR",
    "Croatia": "HR",
    "Denmark": "DK",
    "Dominican Republic": "DO",
    "Ecuador": "EC",
    "Egypt": "EG",
    "El Salvador": "SV",
    "Estonia": "EE",
    "Ethiopia": "ET",
    "Finland": "FI",
    "France": "FR",
    "Germany": "DE",
    "Great Britain": "GB",
    "Guatemala": "GT",
    "Hong Kong": "HK",
    "India": "IN",
    "Indonesia": "ID",
    "Ireland": "IE",
    "Israel": "IL",
    "Italy": "IT",
    "Japan": "JP",
    "Jordan": "JO",
    "Latvia": "LV",
    "Luxembourg": "LU",
    "Malaysia": "MY",
    "Mexico": "MX",
    "Netherlands Antilles": "AN",
    "New Zealand": "NZ",
    "Nigeria": "NG",
    "Norway": "NO",
    "Panama": "PA",
    "Paraguay": "PY",
    "Peru": "PE",
    "Philippines": "PH",
    "Poland": "PL",
    "Pr of China": "CN",
    "Romania": "RO",
    "Saudi Arabia": "SA",
    "Singapore": "SG",
    "South Korea": "KR",
    "Spain": "ES",
    "Sri Lanka": "LK",
    "Sweden": "SE",
    "Switzerland": "CH",
    "Taiwan R.O.C.": "TW",
    "Thailand": "TH",
    "The Netherlands": "NL",
    "Togo": "TG",
    "Turkey": "TR",
    "U.S.A.": "US",
    "United Arab Emirates": "AE",
    "Uruguay": "UY",
    "Venezuela": "VE",
    "Vietnam": "VN",
}


def get_country_iso(country_name: str | None) -> str | None:
    """Return the ISO2 code for a sheet country name, or ``None`` if unmapped."""
    if not country_name:
        return None
    return COUNTRY_TO_ISO.get(country_name.strip())
