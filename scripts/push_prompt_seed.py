#!/usr/bin/env python3
"""Bootstrap: push managed prompts to LangSmith Hub."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langsmith import Client
from langsmith.utils import LangSmithConflictError

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
load_dotenv(_REPO_ROOT / ".env", override=False)

from app.core.config import settings  # noqa: E402
from app.domain.prompt_hub_refs import (  # noqa: E402
    CARRIER_ACK_CLASSIFY_PROMPT,
    DRIVER_DETAILS_EXTRACT_PROMPT,
    POD_PAGE_EXTRACTION_PROMPT,
    POD_VS_RATECON_SEMANTIC_MATCH_PROMPT,
    POD_VS_RATECON_SUMMARY_PROMPT,
    RATECON_PAGE_EXTRACTION_PROMPT,
    hub_prompt_id,
)
from app.domain.pod_lifecycle.vs_ratecon_prompt_templates import (  # noqa: E402
    build_pod_vs_ratecon_semantic_match_seed_prompt,
    build_pod_vs_ratecon_summary_seed_prompt,
)
from app.domain.vision_prompt_templates import (  # noqa: E402
    build_pod_page_seed_prompt,
    build_ratecon_page_seed_prompt,
)

CARRIER_ACK_SYSTEM = """
You analyze a load-tender email conversation and decide its current operational state.
Return JSON only:
{{"decision": string, "confidence": number, "reason": string}}

decision must be exactly one of:
- "accepted"
- "rejected"
- "do_nothing"

INPUT
You receive a chronological email thread. Each email is labeled:
email N [direction | from: <address> | to: <addresses>].
Use the from/to headers to attribute each statement to a sender.
There is no fixed rule about which side accepts: commitment can come from EITHER party.
Read the WHOLE thread. Weigh the latest SUBSTANTIVE operational message; ignore quoted
history, forward headers (From/Sent/To/Subject blocks), signatures, disclaimers, and bare
courtesy lines when earlier messages already settle the state.

DECISIONS
"accepted": the thread shows the load is operationally committed and NO tender-level action is
still open. Commitment may be a party confirming they will take/cover/dispatch the load, or a
party agreeing to handle the outstanding step. Examples of commitment language:
"confirmed", "we can cover", "driver assigned", "will pick up", "we'll take care of it",
"we've got this one", "booked".

"rejected": a party clearly declines or cannot handle the load.
Examples: "cannot cover", "pass", "no truck", "unable", "declined".

"do_nothing": the conversation is still OPEN or carries no operational decision. Use it for:
open questions or requests awaiting a reply (e.g. "can you send/create the BOL?"),
in-progress back-and-forth, missing-information asks, out-of-office, attachment-only emails,
and thank-you / acknowledgement lines when commitment has NOT already been established.

GUIDANCE
- Attribute each statement to its sender via the from/to headers; do not assume the latest sender is the carrier.
- A request directed AT a party is not that party accepting; it is an open item -> "do_nothing".
- Prefer operational intent over literal wording.
- confidence must be between 0.0 and 1.0 and reflect how clearly the thread supports the decision.
- reason must be one short sentence and must be consistent with the decision.

EXAMPLES
- Vendor: "I have a carrier set for this one. Could you please create the BOL?" with no later reply
  -> {{"decision": "do_nothing", "confidence": 0.8, "reason": "Vendor asks the shipper to create the BOL; request still open."}}
- Vendor asks shipper to create the BOL, then shipper replies "We'll take care of it."
  -> {{"decision": "accepted", "confidence": 0.9, "reason": "Shipper committed to handle the load."}}
- Vendor: "Confirmed, driver assigned."
  -> {{"decision": "accepted", "confidence": 0.95, "reason": "Vendor confirmed and assigned a driver."}}
- Vendor: "Thanks!" after the load was already committed
  -> {{"decision": "do_nothing", "confidence": 0.7, "reason": "Courtesy reply with no new operational decision."}}
""".strip()


def build_carrier_ack_seed_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", CARRIER_ACK_SYSTEM),
            ("human", "{thread_text}"),
        ]
    )


DRIVER_DETAILS_SYSTEM = """
You extract driver contact details from carrier email replies to a driver assignment request.
Return JSON only:
{{"decision": string, "confidence": number, "reason": string, "driver": {{"name": string|null, "phone": string|null, "email": string|null}}}}

decision must be exactly one of:
- "has_details"
- "insufficient"
- "do_nothing"

The user message is a chronological email thread labeled email 1, email 2, and so on (oldest to newest).
Base your extraction primarily on the latest carrier message; use earlier messages only as context.
Ignore quoted history, internal reminders, signatures, and non-operational boilerplate when the latest message is clear.

Use "has_details" when the latest carrier message clearly provides a driver name and at least one contact method (phone or email) with intent to assign or confirm the driver for the load.

Use "insufficient" when only a name or only contact is given, details are ambiguous, or the carrier says they will send later.

Use "do_nothing" for questions, unrelated messages, thank-you only, out-of-office, attachment-only with no usable text, or no driver assignment intent.

Use JSON null for missing driver fields, not the string "null".
confidence must be between 0.0 and 1.0.
reason must be one short sentence.
""".strip()


def build_driver_details_seed_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", DRIVER_DETAILS_SYSTEM),
            ("human", "{thread_text}"),
        ]
    )


def _langsmith_client() -> Client:
    api_key = (settings.LANGSMITH_API_KEY or "").strip()
    if not api_key:
        print(
            "LANGSMITH_API_KEY is not set. Add it to .env or export it, then retry.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    return Client(api_key=api_key)


def _hub_id(prompt_name: str) -> str:
    return hub_prompt_id(prompt_name, owner=settings.LANGSMITH_PROMPT_OWNER)


def push_prompt(client: Client, prompt_name: str, template: ChatPromptTemplate) -> str:
    prompt_id = _hub_id(prompt_name)
    try:
        url = client.push_prompt(
            prompt_id,
            object=template,
            tags=["staging"],
            commit_tags=["staging"],
            commit_description="FreightX managed vision extraction prompt",
        )
    except LangSmithConflictError:
        print(f"Skipped {prompt_id}: unchanged since latest commit")
        return prompt_id
    print(f"Pushed {prompt_id} -> {url}")
    return prompt_id


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--prompt",
        choices=[
            "carrier-ack",
            "driver-details",
            "pod",
            "ratecon",
            "pod-vs-ratecon",
            "pod-vs-ratecon-semantic",
            "all",
        ],
        default="all",
        help="Which prompt(s) to push (default: all)",
    )
    args = parser.parse_args()
    client = _langsmith_client()

    targets: list[tuple[str, ChatPromptTemplate]] = []
    if args.prompt in ("carrier-ack", "all"):
        targets.append((CARRIER_ACK_CLASSIFY_PROMPT, build_carrier_ack_seed_prompt()))
    if args.prompt in ("driver-details", "all"):
        targets.append((DRIVER_DETAILS_EXTRACT_PROMPT, build_driver_details_seed_prompt()))
    if args.prompt in ("pod", "all"):
        targets.append((POD_PAGE_EXTRACTION_PROMPT, build_pod_page_seed_prompt()))
    if args.prompt in ("ratecon", "all"):
        targets.append((RATECON_PAGE_EXTRACTION_PROMPT, build_ratecon_page_seed_prompt()))
    if args.prompt in ("pod-vs-ratecon", "all"):
        targets.append(
            (POD_VS_RATECON_SUMMARY_PROMPT, build_pod_vs_ratecon_summary_seed_prompt())
        )
    if args.prompt in ("pod-vs-ratecon-semantic", "all"):
        targets.append(
            (
                POD_VS_RATECON_SEMANTIC_MATCH_PROMPT,
                build_pod_vs_ratecon_semantic_match_seed_prompt(),
            )
        )

    for prompt_name, template in targets:
        push_prompt(client, prompt_name, template)

    print("Tag production in the LangSmith UI when ready for prod tenants.")
    if not (settings.LANGSMITH_PROMPT_OWNER or "").strip():
        print(
            "Tenant settings should use refs like "
            f"{POD_PAGE_EXTRACTION_PROMPT}:staging (no owner prefix)."
        )


if __name__ == "__main__":
    main()
