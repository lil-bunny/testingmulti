"""Tests for PromptService tenant prompt resolution."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.integrations.langsmith import MissingTenantPromptRefError
from app.integrations.langsmith.types import (
    PromptLoadMetadata,
    PromptTraceMetadata,
    RenderedPrompt,
)
from app.domain.prompt_step_keys import LOAD_TENDERING_CARRIER_ACK
from app.services.prompt_service import PromptService


def test_render_step_resolves_nested_prompt_ref() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="sys", user="usr"),
        PromptLoadMetadata(
            source="hub",
            tenant_prompt_ref="carrier-ack-classify:production",
            commit_hash="abc123",
        ),
    )
    prompt_service = PromptService(prompt_client=client)
    rendered, metadata = prompt_service.render_step(
        tenant_settings={
            "prompts": {
                "load_tendering": {
                    "carrier_ack": "carrier-ack-classify:production",
                }
            }
        },
        prompt_step_key=LOAD_TENDERING_CARRIER_ACK,
        variables={"thread_text": "email 1\nok"},
    )
    assert rendered.system == "sys"
    assert rendered.user == "usr"
    assert metadata.source == "hub"
    assert metadata.tenant_prompt_ref == "carrier-ack-classify:production"
    assert metadata.commit_hash == "abc123"
    client.load_and_render.assert_called_once_with(
        "carrier-ack-classify:production",
        {"thread_text": "email 1\nok"},
    )


def test_prompt_trace_metadata_for_langsmith() -> None:
    load = PromptLoadMetadata(
        source="hub",
        tenant_prompt_ref="carrier-ack-classify:production",
        commit_hash="abc123",
    )
    trace = PromptTraceMetadata.from_load(LOAD_TENDERING_CARRIER_ACK, load)
    meta = trace.to_langsmith_metadata()
    assert meta["prompt_step_key"] == LOAD_TENDERING_CARRIER_ACK
    assert meta["tenant_prompt_ref"] == "carrier-ack-classify:production"
    assert meta["prompt_source"] == "hub"
    assert meta["prompt_commit_hash"] == "abc123"


def test_render_step_missing_ref_raises() -> None:
    prompt_service = PromptService(prompt_client=MagicMock())
    with pytest.raises(MissingTenantPromptRefError):
        prompt_service.render_step(
            tenant_settings={"prompts": {}},
            prompt_step_key=LOAD_TENDERING_CARRIER_ACK,
            variables={"thread_text": "x"},
        )
