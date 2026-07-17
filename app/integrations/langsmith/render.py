"""Render LangChain prompt templates to system + user strings."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from langchain_core.messages import BaseMessage

from app.integrations.langsmith.types import RenderedPrompt

if TYPE_CHECKING:
    from langchain_core.prompts import BasePromptTemplate


def render_system_user(
    template: BasePromptTemplate,
    variables: dict[str, Any],
) -> RenderedPrompt:
    """
    Format a ChatPromptTemplate and return the first system and human contents.

    Pilot assumes a single system message and a single human message.
    """
    messages = template.format_messages(**variables)
    system_text = ""
    user_text = ""
    for message in messages:
        if not isinstance(message, BaseMessage):
            continue
        role = getattr(message, "type", None) or ""
        content = _message_content(message)
        if role == "system" and not system_text:
            system_text = content
        elif role in ("human", "user") and not user_text:
            user_text = content
    return RenderedPrompt(system=system_text, user=user_text)


def _message_content(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts)
    return str(content or "")
