"""
End-to-end tests for the ``load_tendering`` workflow graph.

Runs ``WorkflowService.run()`` in-process against the real DB and the real graph.
Mocks exactly two boundaries: the carrier-ack LLM call (``chat_json``) and the
Unipile send (``send_email``). Everything else, tender creation, soft-fail
handling, routing guide failover, reminder scheduling, escalation, runs for real.

This suite checks that OUR logic reacts correctly to a given LLM answer, not
whether the LLM's answer is correct. Model-quality testing belongs in the eval
dataset (LangSmith), not here.

Scenario variety mirrors real production traces (LangSmith "Gelita Load
Tendering" / "LLM Carrier Email Ack" datasets), reproduced as synthetic data,
not literal copies: 4 real tender_created soft-fail error codes were found
missing_delivery_address, missing_pack_code, missing_pallet_dims,
missing_unit_dims, plus the 3 possible carrier-ack decisions and an
LLM-call-failure case.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest.mock import patch

import psycopg
import pytest

from app.core.config import settings
from app.repositories.tenant_repo import TenantRepository
from app.repositories.workflow_repo import WorkflowRepository
from app.services.workflow_reminder_cancel_service import WorkflowReminderCancelService
from app.services.workflow_service import WorkflowService
from app.tools.llm_client import LLMClientError

# `app.domain.tenant_settings.gelita` types its models against classes it only imports
# under `TYPE_CHECKING`; nothing in the app calls `model_rebuild()`, it happens to resolve
# in production only as a side effect of the full app import graph. Force it here so this
# test file works standalone.
from app.domain.reminder_schedule import WorkflowRemindersConfig
from app.domain.tenant_settings.email_recipients import EmailRecipients, InboundRoutingEmails
from app.domain.tenant_settings.workflow_error_alerts import WorkflowErrorAlertSettings
from app.domain.tenant_settings import gelita as _gelita_settings

for _model in (
    _gelita_settings.GelitaSendTenderEmailSettings,
    _gelita_settings.GelitaEscalateTenderSettings,
    _gelita_settings.GelitaLoadTypeBranch,
    _gelita_settings.GelitaLoadTenderingSettings,
    _gelita_settings.GelitaTenantSettings,
):
    _model.model_rebuild(
        _types_namespace={
            "WorkflowRemindersConfig": WorkflowRemindersConfig,
            "EmailRecipients": EmailRecipients,
            "InboundRoutingEmails": InboundRoutingEmails,
            "WorkflowErrorAlertSettings": WorkflowErrorAlertSettings,
        },
        force=True,
    )


def _dsn() -> str:
    return settings.DATABASE_URL.replace("postgresql+psycopg://", "postgresql://")


def _load_type_branch(to_email: str, *, include_products_block: bool = False) -> dict[str, Any]:
    template = "<p>{reason_for_failure}Tender for order {order_number}</p>"
    if include_products_block:
        # {products_block} is what actually carries per-product lines (incl. unit_dims)
        # into the rendered body (build_ltl_tender_email_from_tender /
        # build_ftl_tender_email_from_tender in app/tools/tender_email.py). Left out of
        # the default template above since most tests here only check that an email
        # went out, not its contents.
        template = (
            "<p>{reason_for_failure}Tender for order {order_number}</p>"
            "<div>{products_block}</div>"
        )
    return {
        "send_tender_email": {
            "emails": {"to": [to_email], "cc": [], "bcc": []},
            "email_subject": "Tender # {order_number}",
            "email_template_html": template,
        },
        "send_tender_reminder": {
            "reminder_body": "<p>Following up on the request.</p>",
        },
        "escalate_tender": {
            "emails": {"to": [to_email], "cc": [], "bcc": []},
            "escalation_email_body": "<p>Escalation for order {order_number}</p>",
            "escalation_email_subject": "Escalation # {order_number}",
        },
    }


def _tenant_settings_json(
    *,
    carrier_email: str = "carrier@example-test.com",
    skipped_pack_codes: list[str] | None = None,
    include_products_block: bool = False,
) -> dict[str, Any]:
    return {
        "enabledProcesses": ["load_tendering"],
        "inbound_routing_emails": ["ops@example-test.com"],
        "ana_at_gelita_account_id": "test-unipile-account-id",
        "unipile_sent_folder_id": "test-unipile-sent-folder-id",
        "prompts": {"load_tendering": {"carrier_ack": "carrier-ack-classify:e2e-test"}},
        "load_tendering": {
            "ltl": _load_type_branch(carrier_email, include_products_block=include_products_block),
            "ftl": {
                **_load_type_branch(carrier_email, include_products_block=include_products_block),
                "max_attempts": 3,
            },
            "reminders": {
                "variants": {
                    "ftl": [
                        {"step": 1, "event_type": "reminder_due", "delay_hours": 0.016},
                        {"event_type": "escalation_due", "delay_hours": 0.03},
                    ],
                    "ltl": [
                        {"step": 1, "event_type": "reminder_due", "delay_hours": 0.016},
                        {"step": 2, "event_type": "reminder_due", "delay_hours": 0.05},
                        {"event_type": "escalation_due", "delay_hours": 0.06},
                    ],
                },
                "variant_selector": "load_type",
                "skip_sub_statuses": ["accepted", "rejected"],
                "expire_grace_hours": 2,
                "schedule_on_event_type": "carrier_email_received",
                "delivery_cutoff": {"local_time": "13:00", "timezone": "America/Chicago"},
            },
            "tender_calculate": {
                "pallet_profiles": {
                    "wood_4way": {
                        "weight_lbs": 50,
                        "threshold": 8,
                        "default": True,
                        "match": ["4-way wood", "2-way wood"],
                    },
                },
                "gelita_pickup_address": {
                    "city": "Test City",
                    "name": "TEST SHIPPER",
                    "state": "IA",
                    "country": "United States",
                    "address1": "123 Test Rd",
                    "postal_code": 51054,
                },
            },
            "domestic_delivery": {"country_iso_codes": ["US", "CA", "MX"]},
            "skipped_pack_codes": {"pack_codes": skipped_pack_codes or []},
            "workflow_error_alerts": {
                "enabled": True,
                "channels": [
                    {
                        "channel": "email",
                        "to": ["ops-alerts@example-test.com"],
                        "cc": [],
                        "bcc": [],
                        "subject": "Exception: Order Processing Failure PO {customer_po}",
                        "body_template": "<p>Failure: {failure_reason} Order: {order_number}</p>",
                    }
                ],
            },
        },
    }


@pytest.fixture
def test_tenant(request):
    """Insert a synthetic tenant for one test, clean up after (rows + pack_codes).

    Optional indirect param, e.g. ``@pytest.mark.parametrize("test_tenant",
    [{"skipped_pack_codes": ["FOO"]}], indirect=True)``, to override settings that
    the default tenant doesn't need (kept off by default so most tests don't have to
    think about it).
    """
    overrides = getattr(request, "param", None) or {}
    tenant_id = str(uuid.uuid4())
    slug = f"e2e-lt-{uuid.uuid4().hex[:8]}"
    dsn = _dsn()
    with psycopg.connect(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenants (id, name, slug, settings) VALUES (%s, %s, %s, %s::jsonb)",
                (
                    tenant_id,
                    "E2E Load Tendering Test",
                    slug,
                    json.dumps(_tenant_settings_json(**overrides)),
                ),
            )
    try:
        yield {"id": tenant_id, "slug": slug}
    finally:
        with psycopg.connect(dsn) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM workflow_lifecycles WHERE tenant_id = %s", (tenant_id,)
                )
                lifecycle_ids = [row[0] for row in cur.fetchall()]
        # carrier_email_received schedules Celery ETA tasks that outlive this fixture;
        # a slow suite run can let one fire after the tenant row below is gone (tenant
        # not found). Revoke whatever's still pending before deleting anything.
        for lifecycle_id in lifecycle_ids:
            WorkflowReminderCancelService().cancel_all(lifecycle_id=str(lifecycle_id))
        with psycopg.connect(dsn) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("DELETE FROM communications WHERE tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM workflow_runs WHERE tenant_id = %s", (tenant_id,))
                cur.execute(
                    "DELETE FROM workflow_lifecycles WHERE tenant_id = %s", (tenant_id,)
                )
                cur.execute("DELETE FROM tender_products WHERE tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM tenders WHERE tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM pack_codes WHERE tenant_id = %s", (tenant_id,))
                cur.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))


def _seed_pack_code(
    tenant_id: str,
    *,
    pack_code: str,
    units_per_pallet: float | None = 10,
    qty_per_unit: float | None = 1,
    total_qty: float | None = 10,
    unit_dims: str | None = "10x10x10",
    pallet_dims: str | None = "48x40x60",
    pallet_type: str | None = "wood_4way",
    pack_type: str | None = "case",
    pack_type_weight: float | None = 5,
) -> str:
    """Insert a pack_codes row, return its id (FK target for tender_products.pack_code_id)."""
    pack_code_id = str(uuid.uuid4())
    with psycopg.connect(_dsn()) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pack_codes
                    (id, tenant_id, pack_code, is_active, units_per_pallet, qty_per_unit,
                     total_qty, unit_dims, pallet_dims, pallet_type, pack_type, pack_type_weight)
                VALUES (%s, %s, %s, true, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    pack_code_id,
                    tenant_id,
                    pack_code,
                    units_per_pallet,
                    qty_per_unit,
                    total_qty,
                    unit_dims,
                    pallet_dims,
                    pallet_type,
                    pack_type,
                    pack_type_weight,
                ),
            )
    return pack_code_id


def _seed_tender_product(
    tenant_id: str,
    *,
    tender_id: str,
    pack_code_id: str | None,
    product_name: str = "Test Product",
    order_quantity: float = 10,
    weight_unit: str = "lbs",
) -> None:
    with psycopg.connect(_dsn()) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO tender_products
                    (id, tenant_id, tender_id, pack_code_id, product_name, order_quantity,
                     weight_unit, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, '{}'::jsonb)
                """,
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    tender_id,
                    pack_code_id,
                    product_name,
                    order_quantity,
                    weight_unit,
                ),
            )


def _seed_carrier_email_received_communication(
    tenant_id: str,
    *,
    workflow_lifecycle_id: str,
    thread_id: str,
) -> None:
    """send_tender_reminder resolves the carrier thread via a real `communications` row
    joined to a `workflow_runs` row with event_type='carrier_email_received'
    (app/repositories/communications_repository.py:_carrier_anchors_ranked_sql). Without
    this, it safely skips instead of replying (see test_reminder_due_without_resolvable_
    thread_skips_safely). This seeds the minimum needed for it to actually resolve."""
    run_id = str(uuid.uuid4())
    with psycopg.connect(_dsn()) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workflow_runs (id, tenant_id, workflow_lifecycle_id, event_type) "
                "VALUES (%s, %s, %s, 'carrier_email_received')",
                (run_id, tenant_id, workflow_lifecycle_id),
            )
            cur.execute(
                "INSERT INTO communications "
                "(id, tenant_id, channel, direction, thread_id, content, workflow_run_id, "
                " workflow_lifecycle_id) "
                "VALUES (%s, %s, 'email', 'inbound', %s, %s, %s, %s)",
                (
                    str(uuid.uuid4()),
                    tenant_id,
                    thread_id,
                    "Got it, checking on this.",
                    run_id,
                    workflow_lifecycle_id,
                ),
            )


def _tender(
    *,
    order_number: str = "10001",
    pack_code: str = "PACK1",
    delivery_address_code: str = "DELV1",
    po_number: str = "PO-1",
    customer_name: str = "TEST CUSTOMER",
) -> dict[str, Any]:
    return {
        "pack_code": pack_code,
        "po_number": po_number,
        "order_number": order_number,
        "customer_name": customer_name,
        "tender_products": [],
        "delivery_address_code": delivery_address_code,
    }


def _seed_tender(
    tenant_id: str,
    *,
    tender_id: str,
    order_number: str,
    customer_name: str = "TEST CUSTOMER",
    delivery_address: dict | None = None,
    load_type: str = "LTL",
) -> None:
    """The real ingestion path creates ``tenders`` rows (and ``tender_products``) from the
    xlsx before the graph ever runs; ``read_tender_row`` always re-reads fresh from these
    tables (LEFT JOIN pack_codes), so the payload's own ``tender`` dict is not authoritative,
    real DB rows are. Since this suite skips ingestion, seed them directly.

    ``delivery_date`` is required by ``read_tender_row`` for every event except
    ``tender_created`` (``BusinessError.MISSING_DELIVERY_DATE`` otherwise), so it's always
    set here even though it's unrelated to any of the soft-fail cases this suite covers.

    ``load_type`` matters for rejections specifically: routing-guide carrier failover
    (``routing_guide_router`` in app/workflows/graph/routers.py) only applies to FTL,
    a rejected LTL tender is always terminal, no next-carrier attempt.
    """
    with psycopg.connect(_dsn()) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO tenders "
                "(id, tenant_id, order_number, customer_name, delivery_address, "
                " shipping_date, delivery_date, load_type) "
                "VALUES (%s, %s, %s, %s, %s::jsonb, CURRENT_DATE, CURRENT_DATE + 3, %s)",
                (
                    tender_id,
                    tenant_id,
                    order_number,
                    customer_name,
                    json.dumps(delivery_address) if delivery_address else None,
                    load_type,
                ),
            )


async def _run(tenant: dict, payload: dict) -> dict:
    service = WorkflowService(
        workflow_repo=WorkflowRepository(),
        tenant_repo=TenantRepository(),
    )
    return await service.run(
        tenant_slug=tenant["slug"],
        workflow_name="load_tendering",
        payload=payload,
    )


@pytest.fixture
def mock_send_email():
    with patch("app.workflows.nodes.send_tender_email.send_email") as mocked:
        mocked.return_value = {"success": True, "message_id": "mock-msg-id"}
        yield mocked


@pytest.fixture
def mock_carrier_ack(request):
    """Patch the carrier-ack LLM call. Param via @pytest.mark.parametrize or set .return_value/.side_effect."""
    with patch("app.tools.carrier_ack.chat_json") as mocked:
        yield mocked


@pytest.fixture
def mock_escalate_email():
    """escalate_tender sends a plain email (no thread lookup needed), separate import
    from send_tender_email's send_email."""
    with patch("app.workflows.nodes.escalate_tender.send_email") as mocked:
        mocked.return_value = {"success": True, "message_id": "mock-escalation-id"}
        yield mocked


@pytest.fixture
def mock_reply_to_thread():
    with patch("app.workflows.nodes.send_tender_reminder.reply_to_thread") as mocked:
        mocked.return_value = {"success": True, "message_id": "mock-reminder-id"}
        yield mocked


def _fetch_lifecycle(lifecycle_id: str) -> dict | None:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, status, sub_status, tender_id, metadata "
                "FROM workflow_lifecycles WHERE id = %s",
                (lifecycle_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


def _fetch_tender(tender_id: str) -> dict | None:
    with psycopg.connect(_dsn()) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, order_number, status FROM tenders WHERE id = %s",
                (tender_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            cols = [d[0] for d in cur.description]
            return dict(zip(cols, row))


# ---------------------------------------------------------------------------
# tender_created
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tender_created_clean_sends_tender_email(test_tenant, mock_send_email):
    tenant_id = test_tenant["id"]
    tender_id = str(uuid.uuid4())
    order_number = "20001"
    pack_code_id = _seed_pack_code(tenant_id, pack_code="PACKCLEAN")
    _seed_tender(
        tenant_id,
        tender_id=tender_id,
        order_number=order_number,
        delivery_address={"city": "Test City", "street": "1 Main St", "zip": "12345"},
    )
    _seed_tender_product(tenant_id, tender_id=tender_id, pack_code_id=pack_code_id)

    payload = {
        "event_type": "tender_created",
        "tender_id": tender_id,
        "order_number": order_number,
        "thread_id": f"thread-{uuid.uuid4().hex[:8]}",
        "tender": _tender(order_number=order_number, pack_code="PACKCLEAN"),
    }

    await _run(test_tenant, payload)

    assert mock_send_email.called, "expected send_tender_email to call send_email"
    call_kwargs = mock_send_email.call_args.kwargs
    assert "carrier@example-test.com" in json.dumps(call_kwargs.get("to") or call_kwargs)
    body_sent = json.dumps(call_kwargs)
    assert order_number in body_sent


@pytest.mark.parametrize(
    "case,has_pack_code,has_delivery_address,pack_code_kwargs",
    [
        # 4 real error codes found in production LangSmith traces (Gelita Load Tendering
        # dataset): tender still sends in every case, with a warning in the email body.
        ("missing_delivery_address", True, False, {}),
        ("missing_pack_code", False, True, {}),
        ("missing_pallet_dims", True, True, {"pallet_dims": None}),
        ("missing_unit_dims", True, True, {"unit_dims": None}),
    ],
)
@pytest.mark.asyncio
async def test_tender_created_soft_fail_still_sends_email(
    test_tenant, mock_send_email, case, has_pack_code, has_delivery_address, pack_code_kwargs
):
    """Mirrors 4 real production error codes: tender still sends, with a warning."""
    tenant_id = test_tenant["id"]
    tender_id = str(uuid.uuid4())
    order_number = f"2{case[:4]}"

    pack_code_id = None
    if has_pack_code:
        pack_code_id = _seed_pack_code(tenant_id, pack_code="PACKSOFT", **pack_code_kwargs)

    _seed_tender(
        tenant_id,
        tender_id=tender_id,
        order_number=order_number,
        delivery_address=(
            {"city": "Test City", "street": "1 Main St", "zip": "12345"}
            if has_delivery_address
            else None
        ),
    )
    _seed_tender_product(tenant_id, tender_id=tender_id, pack_code_id=pack_code_id)

    payload = {
        "event_type": "tender_created",
        "tender_id": tender_id,
        "order_number": order_number,
        "thread_id": f"thread-{uuid.uuid4().hex[:8]}",
    }

    await _run(test_tenant, payload)

    assert mock_send_email.called, f"case={case}: tender should still send on soft-fail"


# ---------------------------------------------------------------------------
# carrier_email_received -> ack_received
# ---------------------------------------------------------------------------


async def _create_tender_then_reply(
    test_tenant,
    _mock_send_email,
    order_number: str,
    *,
    load_type: str = "LTL",
    seed_communication: bool = False,
) -> dict:
    """Helper: run tender_created, then a first carrier reply (binds thread + schedules reminders).

    ``load_type`` on the ``tenders`` row is only a seed value, ``calculate_tender_params``
    recomputes it from actual pallet math during the ``tender_created`` run and overwrites
    the DB column (app/workflows/nodes/gelita/calculate_tender_params.py:362-367). So to
    genuinely end up FTL, the seeded product's quantity must cross the pallet threshold
    (default profile: threshold=8, units_per_pallet=10 here, so >80 units -> FTL); the
    ``load_type`` param name is kept for readability but LTL callers pass a small quantity.

    ``seed_communication=True`` additionally seeds a real ``communications``/``workflow_runs``
    row so ``send_tender_reminder`` can actually resolve the carrier thread (see
    ``_seed_carrier_email_received_communication``); off by default since most callers don't
    need it.
    """
    tenant_id = test_tenant["id"]
    tender_id = str(uuid.uuid4())
    thread_id = f"thread-{uuid.uuid4().hex[:8]}"
    pack_code_id = _seed_pack_code(tenant_id, pack_code="PACKACK")
    _seed_tender(
        tenant_id,
        tender_id=tender_id,
        order_number=order_number,
        delivery_address={"city": "Test City", "street": "1 Main St", "zip": "12345"},
        load_type=load_type,
    )
    order_quantity = 100 if load_type == "FTL" else 10
    _seed_tender_product(
        tenant_id,
        tender_id=tender_id,
        pack_code_id=pack_code_id,
        order_quantity=order_quantity,
    )

    created_payload = {
        "event_type": "tender_created",
        "tender_id": tender_id,
        "order_number": order_number,
        "thread_id": thread_id,
    }
    await _run(test_tenant, created_payload)

    reply_payload = {
        "event_type": "carrier_email_received",
        "tender_id": tender_id,
        "order_number": order_number,
        "thread_id": thread_id,
        "in_reply_to": "outbound-msg-id",
        "body": "Got it, checking on this.",
    }
    reply_result = await _run(test_tenant, reply_payload)

    wl_id = reply_result.get("workflow_lifecycle_id") or (
        reply_result.get("data") or {}
    ).get("workflow_lifecycle_id")

    if seed_communication:
        assert wl_id, f"expected workflow_lifecycle_id in reply result: {reply_result}"
        _seed_carrier_email_received_communication(
            tenant_id,
            workflow_lifecycle_id=wl_id,
            thread_id=thread_id,
        )

    return {
        "tender_id": tender_id,
        "thread_id": thread_id,
        "order_number": order_number,
        "workflow_lifecycle_id": wl_id,
    }


@pytest.mark.asyncio
async def test_ack_received_accepted_marks_lifecycle_complete(
    test_tenant, mock_send_email, mock_carrier_ack
):
    ctx = await _create_tender_then_reply(test_tenant, mock_send_email, "30001")
    mock_carrier_ack.return_value = {
        "decision": "accepted",
        "confidence": 0.95,
        "reason": "carrier confirmed pickup",
    }

    ack_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "body": "Confirmed, we'll pick this up.",
    }
    result = await _run(test_tenant, ack_payload)

    assert mock_carrier_ack.called
    wl_id = result.get("workflow_lifecycle_id") or (result.get("data") or {}).get(
        "workflow_lifecycle_id"
    )
    assert wl_id, f"expected workflow_lifecycle_id in result: {result}"
    lifecycle = _fetch_lifecycle(wl_id)
    assert lifecycle is not None
    assert lifecycle["sub_status"] == "accepted"


@pytest.mark.asyncio
async def test_ack_received_rejected_ftl_advances_routing_guide(
    test_tenant, mock_send_email, mock_carrier_ack
):
    """FTL only: rejection fails over to the next carrier in the routing guide."""
    ctx = await _create_tender_then_reply(
        test_tenant, mock_send_email, "30002", load_type="FTL"
    )
    mock_carrier_ack.return_value = {
        "decision": "rejected",
        "confidence": 0.91,
        "reason": "carrier arranging their own freight, tender will not be used",
    }
    mock_send_email.reset_mock()

    ack_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "body": "Sorry, can't take this one, arranging our own freight.",
    }
    await _run(test_tenant, ack_payload)

    assert mock_carrier_ack.called
    assert mock_send_email.called, "expected FTL routing guide failover to send a new tender email"


@pytest.mark.asyncio
async def test_ack_received_rejected_ltl_is_terminal(
    test_tenant, mock_send_email, mock_carrier_ack
):
    """LTL: rejection is terminal, no next-carrier attempt (routing_guide_router: ltl_terminal)."""
    ctx = await _create_tender_then_reply(
        test_tenant, mock_send_email, "30005", load_type="LTL"
    )
    mock_carrier_ack.return_value = {
        "decision": "rejected",
        "confidence": 0.91,
        "reason": "carrier arranging their own freight, tender will not be used",
    }
    mock_send_email.reset_mock()

    ack_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "body": "Sorry, can't take this one, arranging our own freight.",
    }
    await _run(test_tenant, ack_payload)

    assert mock_carrier_ack.called
    assert not mock_send_email.called, "LTL rejection is terminal, should not fail over"


@pytest.mark.asyncio
async def test_ack_received_rejected_from_gelita_domain_is_terminal(
    test_tenant, mock_send_email, mock_carrier_ack
):
    """FTL: @gelita.com shipper reject completes as rejected — no next-carrier failover."""
    ctx = await _create_tender_then_reply(
        test_tenant, mock_send_email, "30006", load_type="FTL"
    )
    mock_carrier_ack.return_value = {
        "decision": "rejected",
        "confidence": 0.93,
        "reason": "shipper cancelled the tender",
    }
    mock_send_email.reset_mock()

    ack_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "from_attendee": {
            "identifier": "ops@gelita.com",
            "display_name": "Gelita Ops",
        },
        "body": "Tender closed / cancelled.",
    }
    result = await _run(test_tenant, ack_payload)

    assert mock_carrier_ack.called
    assert not mock_send_email.called, (
        "gelita.com reject must not advance routing guide / send next carrier email"
    )
    wl_id = result.get("workflow_lifecycle_id") or (result.get("data") or {}).get(
        "workflow_lifecycle_id"
    )
    assert wl_id, f"expected workflow_lifecycle_id in result: {result}"
    lifecycle = _fetch_lifecycle(wl_id)
    assert lifecycle is not None
    assert lifecycle["status"] == "completed"
    assert lifecycle["sub_status"] == "rejected"


@pytest.mark.asyncio
async def test_ack_received_do_nothing_leaves_state_unchanged(
    test_tenant, mock_send_email, mock_carrier_ack
):
    ctx = await _create_tender_then_reply(test_tenant, mock_send_email, "30003")
    mock_carrier_ack.return_value = {
        "decision": "do_nothing",
        "confidence": 0.86,
        "reason": "carrier asked a clarifying question, no commitment yet",
    }
    mock_send_email.reset_mock()

    ack_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "body": "Can you confirm the pallet dimensions?",
    }
    await _run(test_tenant, ack_payload)

    assert mock_carrier_ack.called
    assert not mock_send_email.called, "do_nothing should not trigger any new email"


@pytest.mark.asyncio
async def test_ack_received_llm_error_fails_closed(
    test_tenant, mock_send_email, mock_carrier_ack
):
    ctx = await _create_tender_then_reply(test_tenant, mock_send_email, "30004")
    mock_carrier_ack.side_effect = LLMClientError("simulated timeout")
    mock_send_email.reset_mock()

    ack_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "body": "Yes, confirmed.",
    }
    await _run(test_tenant, ack_payload)

    assert mock_carrier_ack.called
    assert not mock_send_email.called, "LLM failure should fail closed (do_nothing), not crash"


# ---------------------------------------------------------------------------
# reminder_due / escalation_due
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_escalation_due_ltl_sends_escalation_email(
    test_tenant, mock_send_email, mock_escalate_email
):
    """LTL always escalates on timeout (evaluate_timeout_routing_guide -> ltl_terminal ->
    escalate_tender), no routing-guide complexity. escalate_tender sends a plain ops
    notification email, no communications/thread lookup needed, so this is a real,
    fully-verified send, not just a routing check."""
    ctx = await _create_tender_then_reply(test_tenant, mock_send_email, "40001", load_type="LTL")

    escalation_payload = {
        "event_type": "escalation_due",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
    }
    result = await _run(test_tenant, escalation_payload)

    assert mock_escalate_email.called, "expected escalate_tender to send the ops alert email"
    call_kwargs = mock_escalate_email.call_args.kwargs
    # escalate_tender.emails.to (the load-type branch's own config), not
    # workflow_error_alerts (a separate channel for system exceptions).
    assert "carrier@example-test.com" in json.dumps(call_kwargs.get("to") or call_kwargs)

    wl_id = result.get("workflow_lifecycle_id") or (result.get("data") or {}).get(
        "workflow_lifecycle_id"
    )
    assert wl_id, f"expected workflow_lifecycle_id in result: {result}"
    lifecycle = _fetch_lifecycle(wl_id)
    assert lifecycle is not None
    assert lifecycle["sub_status"] == "escalated"


@pytest.mark.asyncio
async def test_escalation_due_ftl_with_attempts_left_advances_instead(
    test_tenant, mock_send_email, mock_escalate_email
):
    """FTL only escalates once routing-guide attempts are exhausted; with attempts
    remaining, evaluate_timeout_routing_guide routes to advance_carrier_routing_guide
    instead (try the next carrier silently, don't page ops yet)."""
    ctx = await _create_tender_then_reply(test_tenant, mock_send_email, "40002", load_type="FTL")
    mock_send_email.reset_mock()

    escalation_payload = {
        "event_type": "escalation_due",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
    }
    await _run(test_tenant, escalation_payload)

    assert not mock_escalate_email.called, (
        "with routing-guide attempts remaining, FTL should advance to the next carrier, "
        "not escalate to ops yet"
    )
    assert mock_send_email.called, "expected a new tender email to the next carrier instead"


@pytest.mark.asyncio
async def test_reminder_due_without_resolvable_thread_skips_safely(
    test_tenant, mock_send_email, mock_reply_to_thread
):
    """send_tender_reminder resolves the carrier thread via `communications` (anchored on a
    real inbound carrier_email_received row). With no such row seeded here, the correct,
    safe behavior is: no thread found -> no blind reply attempted, no crash. The
    "actually sends a reminder" case is covered separately, below, with the communications
    fixture seeded (test_reminder_due_with_resolvable_thread_sends_reminder)."""
    ctx = await _create_tender_then_reply(test_tenant, mock_send_email, "40003")

    reminder_payload = {
        "event_type": "reminder_due",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "reminder_step": 1,
    }
    await _run(test_tenant, reminder_payload)

    assert not mock_reply_to_thread.called, (
        "no communications row exists for this thread in this suite, "
        "send_tender_reminder should skip safely rather than reply blindly"
    )


@pytest.mark.asyncio
async def test_reminder_due_with_resolvable_thread_sends_reminder(
    test_tenant, mock_send_email, mock_reply_to_thread
):
    """With a real communications row anchoring the carrier thread, send_tender_reminder
    should actually reply in-thread via Unipile."""
    ctx = await _create_tender_then_reply(
        test_tenant, mock_send_email, "40004", seed_communication=True
    )

    reminder_payload = {
        "event_type": "reminder_due",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "reminder_step": 1,
    }
    await _run(test_tenant, reminder_payload)

    assert mock_reply_to_thread.called, "expected send_tender_reminder to reply in-thread"
    call_kwargs = mock_reply_to_thread.call_args.kwargs
    assert call_kwargs.get("thread_id") == ctx["thread_id"]


@pytest.mark.asyncio
async def test_carrier_email_received_binds_thread_and_schedules_reminders(
    test_tenant, mock_send_email
):
    """The first carrier reply (not yet an ack decision) should bind the thread and
    schedule reminder timers, this is normally just a setup step for the ack_received
    tests above; asserted directly here as its own scenario."""
    tenant_id = test_tenant["id"]
    tender_id = str(uuid.uuid4())
    order_number = "40005"
    thread_id = f"thread-{uuid.uuid4().hex[:8]}"
    pack_code_id = _seed_pack_code(tenant_id, pack_code="PACKCER")
    _seed_tender(
        tenant_id,
        tender_id=tender_id,
        order_number=order_number,
        delivery_address={"city": "Test City", "street": "1 Main St", "zip": "12345"},
    )
    _seed_tender_product(tenant_id, tender_id=tender_id, pack_code_id=pack_code_id)

    created_payload = {
        "event_type": "tender_created",
        "tender_id": tender_id,
        "order_number": order_number,
        "thread_id": thread_id,
    }
    await _run(test_tenant, created_payload)
    mock_send_email.reset_mock()

    reply_payload = {
        "event_type": "carrier_email_received",
        "tender_id": tender_id,
        "order_number": order_number,
        "thread_id": thread_id,
        "in_reply_to": "outbound-msg-id",
        "body": "Got it, checking on this.",
    }
    result = await _run(test_tenant, reply_payload)

    data = result.get("data") or result
    assert data.get("reminders_scheduled") is True, (
        f"expected schedule_tender_reminders to run and set reminders_scheduled: {result}"
    )
    wl_id = result.get("workflow_lifecycle_id") or data.get("workflow_lifecycle_id")
    assert wl_id, f"expected workflow_lifecycle_id in result: {result}"
    lifecycle = _fetch_lifecycle(wl_id)
    assert lifecycle is not None
    assert lifecycle["sub_status"] == "tender_sent_to_carrier"


@pytest.mark.asyncio
async def test_carrier_email_received_ltl_schedules_both_reminder_steps(
    test_tenant, mock_send_email
):
    """This fixture's LTL variant configures 2 reminder_due steps plus an escalation_due
    (see reminders.variants.ltl in _tenant_settings_json). WorkflowReminderService.schedule
    enqueues every configured step in one pass at carrier_email_received (not step 2 only
    after step 1 fires), so all 3 Celery tasks should already be on lifecycle metadata
    right after the first carrier reply. The other reminder tests only ever exercise
    step 1; this asserts both LTL steps actually got scheduled, not just "a" reminder."""
    ctx = await _create_tender_then_reply(test_tenant, mock_send_email, "50005", load_type="LTL")

    lifecycle = _fetch_lifecycle(ctx["workflow_lifecycle_id"])
    assert lifecycle is not None
    pending = (lifecycle.get("metadata") or {}).get("pending_reminder_tasks") or []
    reminder_steps = sorted(
        item.get("step") for item in pending if item.get("event_type") == "reminder_due"
    )
    escalation_entries = [item for item in pending if item.get("event_type") == "escalation_due"]

    assert reminder_steps == [1, 2], (
        f"expected both LTL reminder steps scheduled together, got: {pending}"
    )
    assert len(escalation_entries) == 1, f"expected one escalation task scheduled, got: {pending}"


# ---------------------------------------------------------------------------
# Partial-pallet height scaling reflected in the outbound email body
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "test_tenant", [{"include_products_block": True}], indirect=True
)
async def test_tender_created_partial_pallet_scaled_height_in_email_body(
    test_tenant, mock_send_email
):
    """adjust_unit_dims_for_partial_pallet (app/tools/gelita/pallet_dims.py), exercised
    via calculate_tender_params, scales height for a single partial pallet: pallet_dims
    is the empty base ("48x40x6" here, 6in tall), unit_dims is the fully-loaded pallet
    height ("48x40x60", 10 units), pieces_count=5 of units_per_pallet=10 is a genuine
    partial load. Scaled height = 6 + (60-6)*5/10 = 33, floored. That computed value
    overwrites tender_products[i].unit_dims and flows straight into the rendered email
    body (_format_pallets_line in app/tools/tender_email.py), this isn't a no-op
    computation. Single product line on purpose: _combine_product_lines blanks the
    dims text entirely when multiple lines share a product_name with differing dims.
    Needs the {products_block} tenant override, the default fixture template never
    references per-product fields at all."""
    tenant_id = test_tenant["id"]
    tender_id = str(uuid.uuid4())
    order_number = "60003"
    pack_code_id = _seed_pack_code(
        tenant_id,
        pack_code="PACKHEIGHT",
        units_per_pallet=10,
        qty_per_unit=1,
        total_qty=10,
        unit_dims="48x40x60",
        pallet_dims="48x40x6",
    )
    _seed_tender(
        tenant_id,
        tender_id=tender_id,
        order_number=order_number,
        delivery_address={"city": "Test City", "street": "1 Main St", "zip": "12345"},
    )
    _seed_tender_product(
        tenant_id,
        tender_id=tender_id,
        pack_code_id=pack_code_id,
        order_quantity=5,
    )

    payload = {
        "event_type": "tender_created",
        "tender_id": tender_id,
        "order_number": order_number,
        "thread_id": f"thread-{uuid.uuid4().hex[:8]}",
    }
    await _run(test_tenant, payload)

    assert mock_send_email.called, "expected send_tender_email to call send_email"
    # _format_pallets_line HTML-escapes the dims text before embedding it in the body
    # (it's HTML), so the literal `"` comes through as `&quot;`, not a raw quote.
    body_sent = json.dumps(mock_send_email.call_args.kwargs)
    expected_dims = "48&quot;x40&quot;x33&quot;"
    assert expected_dims in body_sent, (
        f"expected scaled partial-pallet height {expected_dims} in the email body: {body_sent}"
    )


# ---------------------------------------------------------------------------
# Pending reminder ETAs: scheduled at carrier_email_received, revoked on ack
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_received_accepted_cancels_pending_reminders(
    test_tenant, mock_send_email, mock_carrier_ack
):
    """carrier_email_received schedules Celery ETA tasks onto lifecycle metadata
    (WorkflowReminderService.schedule -> WorkflowReminderCancelService.register_tasks).
    record_ack_received cancels all of them once a decision is definitive
    (app/workflows/nodes/record_ack_received.py). Assert both halves: something was
    actually pending first, then it's gone after accept."""
    ctx = await _create_tender_then_reply(test_tenant, mock_send_email, "50001")

    before = _fetch_lifecycle(ctx["workflow_lifecycle_id"])
    assert before is not None
    pending_before = (before.get("metadata") or {}).get("pending_reminder_tasks") or []
    assert pending_before, "expected carrier_email_received to leave pending reminder tasks"

    mock_carrier_ack.return_value = {
        "decision": "accepted",
        "confidence": 0.95,
        "reason": "carrier confirmed pickup",
    }
    ack_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "body": "Confirmed, we'll pick this up.",
    }
    await _run(test_tenant, ack_payload)

    after = _fetch_lifecycle(ctx["workflow_lifecycle_id"])
    assert after is not None
    pending_after = (after.get("metadata") or {}).get("pending_reminder_tasks") or []
    assert pending_after == [], (
        f"expected accept to revoke all pending reminder tasks, still pending: {pending_after}"
    )


@pytest.mark.asyncio
async def test_reminder_due_after_ack_accepted_skips(
    test_tenant, mock_send_email, mock_carrier_ack, mock_reply_to_thread
):
    """delayed_workflow_step_skip_reason (app/tools/load_tendering_lifecycle_guards.py)
    re-reads the lifecycle and skips send_tender_reminder once sub_status is terminal.
    Pairs with the cancel test above: even if a stale reminder task fired anyway (a race
    the cancel is meant to close), this guard is the second line of defense. Seed a
    resolvable communications thread so a bug in the guard would show up as a real send,
    not just "no thread to reply to"."""
    ctx = await _create_tender_then_reply(
        test_tenant, mock_send_email, "50002", seed_communication=True
    )
    mock_carrier_ack.return_value = {
        "decision": "accepted",
        "confidence": 0.95,
        "reason": "carrier confirmed pickup",
    }
    ack_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "body": "Confirmed, we'll pick this up.",
    }
    await _run(test_tenant, ack_payload)

    reminder_payload = {
        "event_type": "reminder_due",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "reminder_step": 1,
    }
    await _run(test_tenant, reminder_payload)

    assert not mock_reply_to_thread.called, (
        "reminder_due after an accepted ack should skip, not reply in-thread again"
    )


# ---------------------------------------------------------------------------
# FTL escalation once routing-guide attempts are exhausted
# ---------------------------------------------------------------------------


def _set_routing_guide_attempt(lifecycle_id: str, attempt: int) -> None:
    """Force the lifecycle to the top of the carrier waterfall directly.

    Getting here for real means two reject+advance round trips (1->2->3), already
    exercised by test_ack_received_rejected_ftl_advances_routing_guide. Seed the DB row
    at the ceiling instead, to isolate escalation_due's "exhausted" router branch
    (routing_guide_router, app/workflows/graph/routers.py) from the advance mechanics.
    """
    with psycopg.connect(_dsn()) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE workflow_lifecycles "
                "SET metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb "
                "WHERE id = %s",
                (json.dumps({"routing_guide_attempt": attempt}), lifecycle_id),
            )


@pytest.mark.asyncio
async def test_escalation_due_ftl_exhausted_attempts_escalates(
    test_tenant, mock_send_email, mock_escalate_email
):
    """FTL max_attempts is 3 in this fixture (ftl.max_attempts). With no advances left,
    routing_guide_router routes to "exhausted" instead of "advance": escalate_tender
    should send the ops alert and mark the lifecycle escalated, not fail over to a
    4th carrier that doesn't exist in the waterfall."""
    ctx = await _create_tender_then_reply(test_tenant, mock_send_email, "50003", load_type="FTL")
    _set_routing_guide_attempt(ctx["workflow_lifecycle_id"], 3)
    mock_send_email.reset_mock()

    escalation_payload = {
        "event_type": "escalation_due",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
    }
    result = await _run(test_tenant, escalation_payload)

    assert mock_escalate_email.called, "expected escalate_tender to send once attempts are exhausted"
    assert not mock_send_email.called, "exhausted FTL should not fail over to another carrier"

    wl_id = result.get("workflow_lifecycle_id") or (result.get("data") or {}).get(
        "workflow_lifecycle_id"
    )
    assert wl_id, f"expected workflow_lifecycle_id in result: {result}"
    lifecycle = _fetch_lifecycle(wl_id)
    assert lifecycle is not None
    assert lifecycle["sub_status"] == "escalated"


# ---------------------------------------------------------------------------
# tender_created: international delivery / skipped pack code, resolved manually
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tender_created_international_delivery_resolves_manually(
    test_tenant, mock_send_email
):
    """post_read_tender_router routes a non-domestic delivery country to
    resolve_international_delivery_skip (app/workflows/nodes/gelita/
    resolve_international_delivery_skip.py) instead of calculate_tender_params ->
    send_tender_email. "Germany" resolves to a known ISO2 (DE) not in this fixture's
    domestic_delivery.country_iso_codes (US/CA/MX); an unmapped country string would
    default to domestic (is_domestic_delivery_country treats unknown as True), so this
    has to be a country the lookup actually recognizes."""
    tenant_id = test_tenant["id"]
    tender_id = str(uuid.uuid4())
    order_number = "60001"
    pack_code_id = _seed_pack_code(tenant_id, pack_code="PACKINTL")
    _seed_tender(
        tenant_id,
        tender_id=tender_id,
        order_number=order_number,
        delivery_address={"city": "Berlin", "street": "1 Test St", "country": "Germany"},
    )
    _seed_tender_product(tenant_id, tender_id=tender_id, pack_code_id=pack_code_id)

    payload = {
        "event_type": "tender_created",
        "tender_id": tender_id,
        "order_number": order_number,
        "thread_id": f"thread-{uuid.uuid4().hex[:8]}",
    }
    result = await _run(test_tenant, payload)

    assert not mock_send_email.called, "international delivery should not send a tender email"
    wl_id = result.get("workflow_lifecycle_id") or (result.get("data") or {}).get(
        "workflow_lifecycle_id"
    )
    assert wl_id, f"expected workflow_lifecycle_id in result: {result}"
    lifecycle = _fetch_lifecycle(wl_id)
    assert lifecycle is not None
    assert lifecycle["sub_status"] == "resolved_manually"


# ---------------------------------------------------------------------------
# ack_received on a retired FTL carrier thread
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ack_received_on_retired_ftl_carrier_thread_skips_llm(
    test_tenant, mock_send_email, mock_carrier_ack
):
    """_guard_retired_carrier_thread_ack (app/workflows/nodes/record_ack_received.py)
    compares the inbound thread's own routing-guide attempt against the lifecycle's
    live attempt, not just thread_id equality. It resolves the thread's attempt via a
    real communications/workflow_runs anchor row (thread_attempt_for_lifecycle), same
    as send_tender_reminder's thread lookup, so this needs seed_communication=True,
    same as test_reminder_due_with_resolvable_thread_sends_reminder; without it there's
    nothing to rank and the guard trivially returns False. Reject once to advance the
    lifecycle to attempt 2 (thread A stays anchored at attempt 1), then a second
    ack_received on that same, now-retired thread should be routed to "skipped" by
    automatic_reply_ack_router before classify_carrier_ack ever runs, no LLM call, no
    second status flip."""
    ctx = await _create_tender_then_reply(
        test_tenant, mock_send_email, "50004", load_type="FTL", seed_communication=True
    )
    mock_carrier_ack.return_value = {
        "decision": "rejected",
        "confidence": 0.91,
        "reason": "carrier arranging their own freight, tender will not be used",
    }
    reject_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "body": "Sorry, can't take this one.",
    }
    await _run(test_tenant, reject_payload)
    assert mock_carrier_ack.called, "expected the reject to reach the LLM classifier"
    assert mock_send_email.called, "expected FTL failover to send a new tender email"

    mock_carrier_ack.reset_mock()
    mock_send_email.reset_mock()
    mock_carrier_ack.return_value = {
        "decision": "accepted",
        "confidence": 0.9,
        "reason": "actually we'll take it",
    }
    stale_ack_payload = {
        "event_type": "ack_received",
        "tender_id": ctx["tender_id"],
        "order_number": ctx["order_number"],
        "thread_id": ctx["thread_id"],
        "in_reply_to": "prior-msg-id",
        "body": "Actually, changed my mind, we'll take it.",
    }
    result = await _run(test_tenant, stale_ack_payload)

    assert not mock_carrier_ack.called, "retired thread ack should skip before the LLM call"
    assert not mock_send_email.called, "retired thread ack should not trigger any new email"
    data = result.get("data") or result
    assert data.get("retired_carrier_thread_ack") is True, (
        f"expected the guard to flag this as a retired-thread ack: {result}"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "test_tenant", [{"skipped_pack_codes": ["PACKSKIP"]}], indirect=True
)
async def test_tender_created_skipped_pack_code_resolves_manually(test_tenant, mock_send_email):
    """post_read_tender_router routes a tender whose product matches
    load_tendering.skipped_pack_codes.pack_codes to resolve_pack_code_skip (a distinct
    node from resolve_international_delivery_skip above, reached only once the
    delivery is domestic; see read_tender_row's skipped_pack_codes matching against
    tender_products.pack_code from the pack_codes join)."""
    tenant_id = test_tenant["id"]
    tender_id = str(uuid.uuid4())
    order_number = "60002"
    pack_code_id = _seed_pack_code(tenant_id, pack_code="PACKSKIP")
    _seed_tender(
        tenant_id,
        tender_id=tender_id,
        order_number=order_number,
        delivery_address={"city": "Test City", "street": "1 Main St", "zip": "12345"},
    )
    _seed_tender_product(tenant_id, tender_id=tender_id, pack_code_id=pack_code_id)

    payload = {
        "event_type": "tender_created",
        "tender_id": tender_id,
        "order_number": order_number,
        "thread_id": f"thread-{uuid.uuid4().hex[:8]}",
    }
    result = await _run(test_tenant, payload)

    assert not mock_send_email.called, "skipped pack code should not send a tender email"
    wl_id = result.get("workflow_lifecycle_id") or (result.get("data") or {}).get(
        "workflow_lifecycle_id"
    )
    assert wl_id, f"expected workflow_lifecycle_id in result: {result}"
    lifecycle = _fetch_lifecycle(wl_id)
    assert lifecycle is not None
    assert lifecycle["sub_status"] == "resolved_manually"
