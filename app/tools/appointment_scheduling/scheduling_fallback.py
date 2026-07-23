"""Pure deterministic scheduling fallback (no I/O).

Mirrors AgenticAI ``_intelligent_mock_scheduling`` date math so a Costco/email
delivery date can be computed when the scheduling LLM call fails. Follows the
prompt STEP 2 rule order (distance bands first, then state, then general
distance) and STEP 3-5 calendar-day add + weekend shift.

Stateless and idempotent: same args in, same result out. No DB, no services.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.appointment_scheduling.models import LlmSchedulingDecision

_MAX_WEEKEND_SHIFTS = 10  # ponytail: matches AgenticAI mock guard against infinite loop

# State -> calendar transit days (prompt STEP 2 B). Keyed by both abbreviation
# and full name; Georgia is miles-dependent so handled separately.
_STATE_TRANSIT_DAYS = {
    "CO": 3, "COLORADO": 3,
    "TX": 3, "TEXAS": 3,
    "NV": 1, "NEVADA": 1,
    "AZ": 2, "ARIZONA": 2,
    "NJ": 5, "NEW JERSEY": 5,
    "WA": 2, "WASHINGTON": 2,
    "IL": 4, "ILLINOIS": 4,
    "ID": 2, "IDAHO": 2,
    "OR": 2, "OREGON": 2,
    "NM": 2, "NEW MEXICO": 2,
    "UT": 2, "UTAH": 2,
    "WY": 3, "WYOMING": 3,
}


def transit_days_for(miles: float, dropoff_state: str) -> int:
    """Calendar transit days, following prompt STEP 2 order (A distance bands,
    B state fallback, C general distance)."""
    m = float(miles or 0)

    # A) Distance bands (only defined for >= 900 miles).
    if m > 2400:
        return 5
    if m >= 1801:
        return 4
    if m >= 1201:
        return 3
    if m >= 900:
        return 2

    # B) State-based fallback.
    state = str(dropoff_state or "").strip().upper()
    if state in ("GA", "GEORGIA"):
        return 4 if m < 1500 else 5
    if state in _STATE_TRANSIT_DAYS:
        return _STATE_TRANSIT_DAYS[state]

    # C) General distance fallback.
    if m < 500:
        return 1
    return 2


def compute_delivery_calendar(
    pickup_mm_dd_yyyy: str, transit_days: int
) -> tuple[str, str, bool]:
    """Add calendar ``transit_days`` to pickup, then shift forward off weekends.

    Returns ``(delivery_mm_dd_yyyy, delivery_weekday_upper, weekend_shifted)``.
    On an unparseable pickup date, returns the input unchanged with weekday DAY.
    """
    try:
        pickup = datetime.strptime(pickup_mm_dd_yyyy.strip(), "%m/%d/%Y").date()
    except (ValueError, AttributeError):
        return pickup_mm_dd_yyyy, "DAY", False

    delivery = pickup + timedelta(days=max(0, int(transit_days)))
    shifted = False
    shifts = 0
    while delivery.weekday() >= 5 and shifts < _MAX_WEEKEND_SHIFTS:  # Sat=5, Sun=6
        delivery += timedelta(days=1)
        shifted = True
        shifts += 1

    return delivery.strftime("%m/%d/%Y"), delivery.strftime("%A").upper(), shifted


def fallback_scheduling_decision(
    *, pickup_mm_dd_yyyy: str, miles: float, dropoff_state: str
) -> LlmSchedulingDecision:
    """Deterministic decision used when the scheduling LLM is unavailable."""
    transit_days = transit_days_for(miles, dropoff_state)
    delivery_date, weekday, weekend_shifted = compute_delivery_calendar(
        pickup_mm_dd_yyyy, transit_days
    )
    return LlmSchedulingDecision(
        calculated_delivery_date=delivery_date,
        calculated_delivery_weekday=weekday,
        selected_pickup_date=pickup_mm_dd_yyyy,
        pcs_pickup_date=pickup_mm_dd_yyyy,
        transit_days=transit_days,
        weekend_shifted=weekend_shifted,
    )
