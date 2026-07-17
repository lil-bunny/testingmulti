"""Tests for ``safe_node`` logging and state error handling."""

from __future__ import annotations

import logging


from app.domain.error_catalog import BusinessError, SystemError
from app.domain.state import WorkflowState
from app.exceptions import WorkflowException
from app.workflows.utils.decorators import safe_node
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def _state() -> WorkflowState:
    return WorkflowState(
        tenant_id="tenant-1",
        tenant_slug="gelita",
        execution_id="run-1",
        data={},
    )


@safe_node
def _workflow_error_node(state: WorkflowState) -> WorkflowState:
    raise WorkflowException(BusinessError.MISSING_TENANT_ID)


@safe_node
def _unexpected_error_node(state: WorkflowState) -> WorkflowState:
    raise RuntimeError("boom")


def test_safe_node_logs_workflow_exception_as_warning_without_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        result = _workflow_error_node(_state())

    error = result["data"]["error"]
    assert error["code"] == BusinessError.MISSING_TENANT_ID
    assert error["category"] == BusinessError.CATEGORY.value
    assert error["message"] == BusinessError.MISSING_TENANT_ID.description
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.WARNING
    assert "error_code=missing_tenant_id" in caplog.records[0].message
    assert "Traceback" not in caplog.text


def test_safe_node_logs_unexpected_exception_with_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.ERROR):
        result = _unexpected_error_node(_state())

    error = result["data"]["error"]
    assert error["code"] == SystemError.UNEXPECTED_NODE_FAILURE
    assert error["category"] == SystemError.CATEGORY.value
    assert error["message"] == SystemError.UNEXPECTED_NODE_FAILURE.description
    assert len(caplog.records) == 1
    assert caplog.records[0].levelno == logging.ERROR
    assert caplog.records[0].exc_info is not None
    assert "Traceback" in caplog.text
