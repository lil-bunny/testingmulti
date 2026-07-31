"""Deterministic POD page evidence matching against Turvo PO-owned stops."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

from app.integrations.turvo.pod_inputs import TurvoShipmentPodInputs  # noqa: TC001

_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9]+")


def build_stop_aware_observations(
    pages: Any,
    turvo_inputs: TurvoShipmentPodInputs,
) -> dict[str, Any]:
    """Match page evidence to the one Turvo stop that owns each extracted PO."""
    page_list = [page for page in pages if isinstance(page, dict)] if isinstance(pages, list) else []
    po_matches: dict[str, dict[str, Any]] = {}
    review_reasons: list[str] = []
    matched_by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)

    for po in turvo_inputs.purchase_orders:
        comparisons = []
        for page in page_list:
            if _normalize(po.po_number) not in {_normalize(value) for value in _reference_values(page)}:
                continue
            evidence, match = _stop_evidence(page, po.stop_id, turvo_inputs)
            status = "matched" if match else ("location_mismatch" if _has_evidence(evidence) else "unconfirmed")
            comparison = {
                "page_number": _page_number(page),
                "status": status,
                "location_name": evidence["location_name"],
                "address": evidence["address"],
            }
            comparisons.append(comparison)
            if match:
                matched_by_page[_page_number(page)].append(
                    {"stop_id": po.stop_id, "stop_type": po.stop_type}
                )

        mismatched_pages = [item["page_number"] for item in comparisons if item["status"] == "location_mismatch"]
        matched_pages = [item["page_number"] for item in comparisons if item["status"] == "matched"]
        # Pickup POs remain visible for context, but pickup evidence is not
        # score-bearing and must never create an alert/review reason.
        if po.stop_type != "pickup":
            if mismatched_pages:
                review_reasons.append(
                    f"PO {po.po_number} does not match its Turvo {po.stop_type} stop on page(s) "
                    f"{', '.join(map(str, mismatched_pages))}."
                )
            if not matched_pages:
                if comparisons:
                    review_reasons.append(
                        f"PO {po.po_number} has no page confirming its Turvo {po.stop_type} stop."
                    )
                else:
                    review_reasons.append(f"PO {po.po_number} was not found in the POD packet.")
        po_matches[po.po_number] = {
            "turvo_stop_id": po.stop_id,
            "turvo_stop_type": po.stop_type,
            "page_comparisons": comparisons,
            "matched_pages": matched_pages,
            "mismatched_pages": mismatched_pages,
            "reference_and_stop_match": any(item["status"] == "matched" for item in comparisons),
        }

    return {
        "po_matches": po_matches,
        "review_reasons": review_reasons,
        "delivery_signature_present": _delivery_proof_present(page_list, matched_by_page),
        "pickup_signature_present": _pickup_signature_present(page_list, matched_by_page),
        "stop_times": _aggregate_stop_times(page_list, matched_by_page),
    }


def _stop_evidence(
    page: dict[str, Any],
    stop_id: str,
    turvo_inputs: TurvoShipmentPodInputs,
) -> tuple[dict[str, str], bool]:
    """Find the page location block that belongs to this Turvo stop.

    A page is deliberately not classified as pickup or delivery: one BOL can
    contain several identifiers and both stop locations.
    """
    blocks = _location_blocks(page)
    for block in blocks:
        if _evidence_matches_stop(block, stop_id, turvo_inputs):
            return block, True
    return (blocks[0] if blocks else {"location_name": "", "address": ""}), False


def _location_blocks(page: dict[str, Any]) -> list[dict[str, str]]:
    blocks: list[dict[str, str]] = []
    for block in page.get("location_blocks") or []:
        if isinstance(block, dict):
            blocks.append(
                {
                    "location_name": str(block.get("location_name") or "").strip(),
                    "address": str(block.get("address") or "").strip(),
                }
            )
    if blocks:
        return blocks

    # Existing stored packets remain readable during schema rollout.
    for stop_type in ("pickup", "delivery"):
        details = page.get(f"{stop_type}_details")
        if isinstance(details, dict):
            blocks.append(
                {
                    "location_name": str(details.get("location_name") or "").strip(),
                    "address": str(details.get("address") or "").strip(),
                }
            )
        else:
            stored_packet = _stored_packet_stop_evidence(page, stop_type)
            if _has_evidence(stored_packet):
                blocks.append(stored_packet)
    return blocks


def _stored_packet_stop_evidence(
    page: dict[str, Any],
    stop_type: str,
) -> dict[str, str]:
    """Read the pre-rollout field layout from already-persisted extraction rows."""
    details = page.get(f"{stop_type}_details")
    if isinstance(details, dict):
        return {
            "location_name": str(details.get("location_name") or "").strip(),
            "address": str(details.get("address") or "").strip(),
        }
    keys = (
        ("pickup_location", "pickup_address")
        if stop_type == "pickup"
        else ("destination_location", "destination_address")
    )
    values = {key: "" for key in keys}
    for field in page.get("fields") or []:
        if isinstance(field, dict) and field.get("key") in values:
            values[field["key"]] = str(field.get("value") or "").strip()
    return {"location_name": values[keys[0]], "address": values[keys[1]]}


def _evidence_matches_stop(
    evidence: dict[str, str],
    stop_id: str,
    turvo_inputs: TurvoShipmentPodInputs,
) -> bool:
    stop = next((item for item in turvo_inputs.stops if item.stop_id == stop_id), None)
    if stop is None:
        return False
    return _text_matches(evidence["location_name"], stop.name) or _text_matches(
        evidence["address"], stop.address
    )


def _text_matches(observed: str, expected: str) -> bool:
    observed_tokens = _tokens(observed)
    expected_tokens = _tokens(expected)
    return bool(observed_tokens and expected_tokens and observed_tokens & expected_tokens)


def _tokens(value: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_PATTERN.findall(value) if len(token) >= 3}


def _has_evidence(evidence: dict[str, str]) -> bool:
    return bool(evidence["location_name"] or evidence["address"])


def _reference_values(page: dict[str, Any]) -> list[str]:
    values = []
    for item in page.get("identifiers") or []:
        if isinstance(item, dict) and str(item.get("value") or "").strip():
            values.append(str(item["value"]))
    for item in page.get("reference_ids") or []:
        if isinstance(item, dict) and str(item.get("value") or "").strip():
            values.append(str(item["value"]))
    return values


def _normalize(value: Any) -> str:
    return str(value or "").strip().casefold()


def _page_number(page: dict[str, Any]) -> int:
    value = page.get("page_number")
    return value if isinstance(value, int) else 0


def _has_proof(page: dict[str, Any]) -> bool:
    proof = page.get("proof_of_receipt")
    return isinstance(proof, dict) and bool(
        proof.get("has_receiver_signature")
        or proof.get("has_stamp")
        or proof.get("has_delivery_sticker")
    )


def _delivery_proof_present(page_list: list[dict[str, Any]], matched_by_page: dict[int, list[dict[str, Any]]]) -> bool:
    return any(
        _is_valid_delivery_proof(page)
        and any(item["stop_type"] == "delivery" for item in matched_by_page[_page_number(page)])
        for page in page_list
    )


def _is_valid_delivery_proof(page: dict[str, Any]) -> bool:
    """A delivery stamp/sticker proves receipt without a signature-owner label."""
    proof = page.get("proof_of_receipt")
    if not isinstance(proof, dict):
        return False
    if proof.get("has_stamp") or proof.get("has_delivery_sticker"):
        return True
    return bool(proof.get("has_receiver_signature")) and (
        str(page.get("signature_owner") or "").lower() == "receiver"
    )


def _pickup_signature_present(page_list: list[dict[str, Any]], matched_by_page: dict[int, list[dict[str, Any]]]) -> bool:
    return any(
        _has_proof(page)
        and any(item["stop_type"] == "pickup" for item in matched_by_page[_page_number(page)])
        for page in page_list
    )


def _aggregate_stop_times(
    page_list: list[dict[str, Any]],
    matched_by_page: dict[int, list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    aggregates: dict[str, dict[str, Any]] = {}
    for page in page_list:
        for match in matched_by_page[_page_number(page)]:
            prefix = match["stop_type"]
            for item in page.get("stop_times") or []:
                if not isinstance(item, dict):
                    continue
                check_in = str(item.get(f"{prefix}_checkin_time") or "").strip()
                check_out = str(item.get(f"{prefix}_checkout_time") or "").strip()
                if not (check_in or check_out):
                    continue
                aggregate = aggregates.setdefault(
                    match["stop_id"],
                    {"turvo_stop_id": match["stop_id"], "stop_type": prefix, "observations": []},
                )
                observation = {"check_in": check_in or None, "check_out": check_out or None, "source_pages": [_page_number(page)]}
                if observation not in aggregate["observations"]:
                    aggregate["observations"].append(observation)
    return list(aggregates.values())
