"""Variable builders for Hub-managed POD vs RateCon prompts."""

from __future__ import annotations

import json
from typing import Any


def summary_prompt_variables(
    cross_validation: dict[str, Any],
    pod_analysis: dict[str, Any],
) -> dict[str, str]:
    return {
        "cross_validation_json": json.dumps(cross_validation, indent=2),
        "signature_present": str(pod_analysis.get("signature_present", False)),
        "stamp_present": str(pod_analysis.get("stamp_present", False)),
        "delivery_confirmed": str(pod_analysis.get("delivery_confirmed", False)),
        "delivery_confirmation_reasoning": str(
            pod_analysis.get("delivery_confirmation_reasoning") or ""
        ),
    }


def semantic_match_prompt_variables(
    field_type: str,
    pod_value: str,
    ratecon_value: str,
) -> dict[str, str]:
    return {
        "field_type": field_type,
        "pod_value": pod_value,
        "ratecon_value": ratecon_value,
    }
