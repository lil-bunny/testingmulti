"""Variable builders for Hub-managed POD / ratecon / attachment prompts."""

from __future__ import annotations


def pod_broker_context(broker_name: str | None) -> str:
    if not broker_name:
        return ""
    return (
        f"\n\n🚨 CRITICAL RULE: The broker for this shipment is '{broker_name}'. "
        "This is the freight broker who arranged the shipment, NOT the carrier company. "
        f"\n\n❌ NEVER extract '{broker_name}' or similar variations as the 'carrier_name'. "
        f"\n\n✅ The carrier is the actual trucking company or cargo company that physically "
        f"transported the goods. If you cannot find a different carrier name than '{broker_name}', "
        "then DO NOT extract any carrier information. and mark it as null"
    )


def pod_prompt_variables(broker_name: str | None) -> dict[str, str]:
    name = (broker_name or "").strip()
    return {
        "broker_name": name,
        "broker_context": pod_broker_context(name or None),
    }
