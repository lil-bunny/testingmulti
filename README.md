# FreightX

Python version: `3.11` (project baseline).

## Run API locally

```bash
uv sync
uv run uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/docs`.

## Run in LangGraph Studio

Prereqs:
- Python 3.11+
- LangSmith account + API key

```bash
uv add "langgraph-cli[inmem]"
uv run langgraph dev
```

Then open:
`https://smith.langchain.com/studio/?baseUrl=http://127.0.0.1:2024`

The default Studio graph is configured in `langgraph.json` and loaded from `app/studio.py:studio_graph`.

## Run reminder worker (Celery ETA)

The POD flow schedules two ETA reminders (24h and 48h) when the initial POD request email is sent.

```bash
.venv/bin/celery -A app.celery_app:celery_app worker --loglevel=info
```

```bash windows
uv run celery -A app.celery_app:celery_app worker --loglevel=info --pool=solo
```

## Business DB migrations (Alembic)

Run business table migrations (for example `workflow_correlation`) with:

```bash
.venv/bin/alembic upgrade head
```

Create a new revision:

```bash
.venv/bin/alembic revision -m "your migration message"
```

Note: LangGraph checkpoint tables are still managed by `PostgresSaver.setup()` at runtime. Alembic here is for app/business tables.

Current head: **`20260515_01`** (chain: **`20260513_01`** tenants → **`20260514_01`** imports → **`20260515_01`** tenders).

**`Can't locate revision` (e.g. `20260515_02` / `20260516_01`):** a development database may still have an old **`alembic_version`** row from experiments. After verifying the schema matches this repo (**`tenants`** with **`settings`**, **`data_imports`**, **`tenders`** as needed), run once: **`uv run alembic stamp 20260515_01`**, then **`uv run alembic upgrade head`**.

**Going forward:** do not reuse or delete Alembic revision ids that appear in **`alembic_version`** anywhere you care about; add new revisions at the head instead.

## Test POD_LIFECYCLE E2E
```bash
uv run pytest -c tests/pytest.ini \
  tests/e2e/scenarios/test_ratecon_workflow.py::test_ratecon_email_received_unipile_webhook \
  tests/e2e/scenarios/test_pod_lifecycle_route_complete_workflow.py::test_pod_lifecycle_route_complete_turvo_webhook \
  tests/e2e/scenarios/test_pod_lifecycle_email_received_workflow.py::test_pod_lifecycle_email_received_unipile_webhook \
  -v
```