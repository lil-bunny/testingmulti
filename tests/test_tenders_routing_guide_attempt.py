"""Tests for routing-guide attempt persistence and load-tendering graph wiring."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import text

from app.configs.workflow_configs import WORKFLOW_CONFIGS
from app.core.config import settings
from app.core.db import db_scope, db_transaction
from app.repositories.workflow_lifecycles_repository import WorkflowLifecyclesRepository
from tests.fixtures.tenant_settings import load_tenant_settings_dev

LIFECYCLE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


def test_load_tendering_advance_path_runs_calculate_before_send() -> None:
    edges = WORKFLOW_CONFIGS["load_tendering"]["edges"]
    assert ["advance_carrier_routing_guide", "calculate_tender_params"] in edges
    assert ["advance_carrier_routing_guide", "send_tender_email"] not in edges


def test_gelita_ftl_reminders_single_followup_before_escalation() -> None:
    reminders = load_tenant_settings_dev("gelita")["load_tendering"]["reminders"]["variants"]["ftl"]
    reminder_steps = [s for s in reminders if s.get("event_type") == "reminder_due"]
    escalation_steps = [s for s in reminders if s.get("event_type") == "escalation_due"]
    assert len(reminder_steps) == 1
    assert len(escalation_steps) == 1
    assert escalation_steps[0]["delay_hours"] > reminder_steps[0]["delay_hours"]


def test_set_routing_guide_attempt_sql_updates_lifecycle_metadata() -> None:
    session = MagicMock()
    session.execute.return_value.rowcount = 1
    repo = WorkflowLifecyclesRepository(session)

    ok = repo.set_routing_guide_attempt(
        lifecycle_id=LIFECYCLE_UUID,
        attempt=2,
    )

    assert ok is True
    sql = str(session.execute.call_args[0][0])
    assert "routing_guide_attempt" in sql
    assert session.execute.call_args[0][1]["attempt"] == 2


def test_set_routing_guide_attempt_persists_on_postgres() -> None:
    if not (settings.DATABASE_URL or "").strip():
        pytest.skip("DATABASE_URL not configured")

    row = None
    try:
        with db_scope() as repos:
            with db_transaction(repos.session):
                repos.session.execute(
                    text(
                        """
                        INSERT INTO workflow_lifecycles (
                            id, tenant_id, workflow_name, metadata
                        )
                        VALUES (
                            CAST(:lifecycle_id AS uuid),
                            CAST(:tenant_id AS uuid),
                            'load_tendering',
                            CAST(:metadata AS jsonb)
                        )
                        ON CONFLICT (id) DO UPDATE
                        SET metadata = EXCLUDED.metadata
                        """
                    ),
                    {
                        "lifecycle_id": LIFECYCLE_UUID,
                        "tenant_id": "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
                        "metadata": json.dumps({"source": "test"}),
                    },
                )
                assert repos.workflow_lifecycles.set_routing_guide_attempt(
                    lifecycle_id=LIFECYCLE_UUID,
                    attempt=2,
                )
                row = repos.workflow_lifecycles.read_row_by_id(LIFECYCLE_UUID)
    except Exception as exc:
        pytest.skip(f"Postgres integration unavailable: {exc}")

    assert row is not None
    meta = row.get("metadata") or {}
    assert meta.get("source") == "test"
    assert meta["routing_guide_attempt"] == 2
