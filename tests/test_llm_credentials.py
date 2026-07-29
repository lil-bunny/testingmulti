"""Tests for workflow-scoped LLM credential resolution."""

import pytest

from app.tools import llm_credentials


@pytest.mark.parametrize(
    ("workflow_name", "setting_name"),
    [
        ("pod_lifecycle", "LLM_POD_LIFECYCLE_API_KEY"),
        ("driver_assignment", "LLM_DRIVER_ASSIGNMENT_API_KEY"),
        ("appointment_scheduling", "LLM_APPOINTMENT_SCHEDULING_API_KEY"),
        ("load_tendering", "LLM_LOAD_TENDERING_API_KEY"),
    ],
)
def test_resolve_llm_credentials_by_workflow(
    monkeypatch,
    workflow_name: str,
    setting_name: str,
) -> None:
    monkeypatch.setattr(llm_credentials.settings, "LLM_BASE_URL", " https://llm.test/v1 ")
    monkeypatch.setattr(llm_credentials.settings, setting_name, f" key-{workflow_name} ")

    credentials = llm_credentials.resolve_llm_credentials(
        workflow_name=workflow_name,
        tenant_slug="t3ra",
    )

    assert credentials.base_url == "https://llm.test/v1"
    assert credentials.api_key == f"key-{workflow_name}"


def test_resolve_llm_credentials_rejects_unknown_workflow() -> None:
    with pytest.raises(ValueError, match="Unsupported LLM workflow"):
        llm_credentials.resolve_llm_credentials(workflow_name="unknown")
