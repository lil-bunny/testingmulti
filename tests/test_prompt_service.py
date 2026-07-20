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
from app.domain.prompt_step_keys import (
    APPOINTMENT_SCHEDULING_OPTIMIZATION,
    DRIVER_ASSIGNMENT_DRIVER_DETAILS,
    LOAD_TENDERING_CARRIER_ACK,
)
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


def test_render_step_nested_t3ra_prompt_ref() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="sys", user="usr"),
        PromptLoadMetadata(
            source="hub",
            tenant_prompt_ref="driver-details-extract:staging",
            commit_hash="abc123",
        ),
    )
    prompt_service = PromptService(prompt_client=client)
    rendered, metadata = prompt_service.render_step(
        tenant_settings={
            "prompts": {
                "driver_assignment": {
                    "driver_details": "driver-details-extract:staging",
                }
            }
        },
        prompt_step_key=DRIVER_ASSIGNMENT_DRIVER_DETAILS,
        variables={"thread_text": "Driver John 555-0100"},
    )
    assert rendered.system == "sys"
    assert metadata.tenant_prompt_ref == "driver-details-extract:staging"
    client.load_and_render.assert_called_once_with(
        "driver-details-extract:staging",
        {"thread_text": "Driver John 555-0100"},
    )


def test_render_step_appointment_scheduling_prompt_ref() -> None:
    client = MagicMock()
    client.load_and_render.return_value = (
        RenderedPrompt(system="sched sys", user="sched usr"),
        PromptLoadMetadata(
            source="hub",
            tenant_prompt_ref="scheduling-optimization:staging",
            commit_hash="def456",
        ),
    )
    prompt_service = PromptService(prompt_client=client)
    variables = {"miles": "100", "scheduling_input_json": "{}"}
    rendered, metadata = prompt_service.render_step(
        tenant_settings={
            "prompts": {
                "appointment_scheduling": {
                    "scheduling_optimization": "scheduling-optimization:staging",
                }
            }
        },
        prompt_step_key=APPOINTMENT_SCHEDULING_OPTIMIZATION,
        variables=variables,
    )
    assert rendered.system == "sched sys"
    assert metadata.tenant_prompt_ref == "scheduling-optimization:staging"
    client.load_and_render.assert_called_once_with(
        "scheduling-optimization:staging",
        variables,
    )
