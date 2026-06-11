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
    POD_PAGE_EXTRACTION_PROMPT,
    POD_VS_RATECON_SEMANTIC_MATCH_PROMPT,
    POD_VS_RATECON_SUMMARY_PROMPT,
    RATECON_PAGE_EXTRACTION_PROMPT,
    hub_prompt_id,
)
from app.domain.pod_vs_ratecon_prompt_templates import (  # noqa: E402
    build_pod_vs_ratecon_semantic_match_seed_prompt,
    build_pod_vs_ratecon_summary_seed_prompt,
)
from app.domain.vision_prompt_templates import (  # noqa: E402
    build_pod_page_seed_prompt,
    build_ratecon_page_seed_prompt,
)

CARRIER_ACK_SYSTEM = """
You classify carrier email replies to a load tender request.
Return JSON only:
{{"decision": string, "confidence": number, "reason": string}}
 
decision must be exactly one of:
- "accepted"
- "rejected"
- "do_nothing"
 
The user message is a chronological email thread labeled email 1, email 2, and so on (oldest to newest).
Base your decision primarily on the latest carrier message; use earlier messages only as context.
Ignore quoted history, internal reminders, and non-operational boilerplate when the latest message is clear.
Classify based on operational intent, not exact wording.
Use "accepted" if the carrier explicitly or implicitly indicates they are taking, confirming, covering, dispatching, acknowledging, or moving forward with the load.
Examples:
"accepted", "confirmed", "we can cover", "driver assigned", "will pick up", "got it", "acknowledged", "received", "copy", "noted", "ok"
 
Use "rejected" if the carrier explicitly or implicitly declines or cannot handle the load.
Examples:
"cannot cover", "pass", "no truck", "unable", "declined"

Use "do_nothing" for:
questions, ambiguous replies, unrelated messages, thank-you replies, out-of-office replies, attachment-only emails, or messages without clear operational intent.
 
Prefer intent over literal wording.
confidence must be between 0.0 and 1.0.
reason must be one short sentence
""".strip()


def build_carrier_ack_seed_prompt() -> ChatPromptTemplate:
    return ChatPromptTemplate.from_messages(
        [
            ("system", CARRIER_ACK_SYSTEM),
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
