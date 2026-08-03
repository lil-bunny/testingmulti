# FreightX Agents

Python version: `3.11` (project baseline).

## Prerequisites

* [Docker](https://docs.docker.com/get-docker/)
* [uv](https://docs.astral.sh/uv/getting-started/installation/)
* [ngrok](https://ngrok.com/download), if you're testing Unipile/Turvo webhooks locally. Claim your one free static domain (ngrok's free plan includes this) and use that instead of the random rotating one, otherwise you have to re-register your webhook URLs with Unipile and Turvo every time you restart the tunnel
* Python 3.11+ (uv will manage this for you, you don't need it installed separately)

## Setup

- clone the repo: `git clone {repo-url}`
- copy `.env.example` to `.env` and fill in the values (see "Secrets" below for where to get them)
- start local infra (Postgres, Redis, MinIO). The docker-compose.yml for this lives in `freightx-api`, not here, since both repos read the same DB and bucket:

```bash
cd ../freightx-api
docker-compose up -d
cd -
```

- install dependencies and run migrations:

```bash
uv sync
uv run alembic upgrade head
```

- run the API:

```bash
uv run uvicorn app.main:app --reload --port 8000
```

Open `http://127.0.0.1:8000/docs`.

- run a Celery worker for the queue you're testing (needed for the reminder scheduler and async webhook ingest). T3RA jobs go to `T3RA` (`settings.T3RA_WORK_QUEUE`); others default to `celery` (`settings.DEFAULT_WORK_QUEUE`). You can run the worker for the lane you're working on unless you need both. Use a unique `-n` if you also run Flower.

  - default queue (`celery`)

```bash
uv run celery -A app.celery_app:celery_app worker -n default@%h -Q celery -c 1 --loglevel=info
```

  - T3RA queue (`t3ra`):

```bash
uv run celery -A app.celery_app:celery_app worker -n t3ra@%h -Q t3ra -c 2 --loglevel=info
```

On Windows, add `--pool=solo` (concurrency is then sequential; use `--pool=threads` on the T3RA worker if you need overlapping tasks locally). Do not start one worker with `-Q celery,T3RA` if you are checking queue isolation. Queues are created automatically on first publish or worker bind - nothing to create in Redis by hand.

- optional: run [Flower](https://flower.readthedocs.io/) to watch workers and active tasks (same Redis broker as `.env`):

```bash
uv run celery -A app.celery_app:celery_app flower --port=5555
```

Open `http://127.0.0.1:5555`

## Secrets

`.env` holds real credentials. Never commit it, and follow the secrets policy in `CLAUDE.md`/`.cursor/rules/secrets-policy.mdc`, don't read/print its contents through an AI assistant either.

None of these are things you can generate yourself, ask someone from the dev team for all of them:

* `UNIPILE_API_KEY`, `UNIPILE_DSN`, `UNIPILE_WEBHOOK_SECRET`, needed for anything email related
* `LLM_BASE_URL` and workflow keys `LLM_POD_LIFECYCLE_API_KEY`, `LLM_DRIVER_ASSIGNMENT_API_KEY`, `LLM_APPOINTMENT_SCHEDULING_API_KEY`, and `LLM_LOAD_TENDERING_API_KEY`. Modality models are configured with `LLM_CHAT_MODEL` / `LLM_VISION_MODEL` / `LLM_PDF_MODEL` (LiteLLM gateway aliases; defaults `text` / `doc_processing` / `doc_processing`).
* Turvo sandbox access and partner API credentials, see below

`LANGSMITH_API_KEY` is optional. Local fallback prompts (`prompts/fallbacks/`) are used automatically if this is missing or doesn't have access to the prompt Hub, so the app works fine without it. If you want working traces/prompt pulls, you need to be invited into the team's LangSmith organization, a personal LangSmith signup won't have access to the team's prompts.

### Unipile

Once you have the API key above, connect your own email account for testing. Emails need to arrive at an inbox Unipile actually has access to, it can't see mail sent to an address it doesn't control:

```bash
uv run python -c "
from app.core.config import settings
import httpx, json
headers = {'X-API-KEY': settings.UNIPILE_API_KEY, 'Accept': 'application/json', 'Content-Type': 'application/json'}
body = {'type': 'create', 'providers': ['GOOGLE'], 'api_url': f'https://{settings.UNIPILE_DSN}', 'name': 'your-name-here'}
r = httpx.post(f'https://{settings.UNIPILE_DSN}/api/v1/hosted/accounts/link', headers=headers, json=body, timeout=20)
print(json.dumps(r.json(), indent=2))
"
```

Open the printed URL, sign in with whichever email you want to listen on for testing, and grant access. Then find your new account id:

```bash
uv run python scripts/manage_unipile_webhook.py accounts
```

Start ngrok (claim your free static domain first, see Prerequisites above), keep it running in its own terminal for everything below:

```bash
ngrok http 8000 --domain=your-domain.ngrok-free.app
```

Then point a webhook at your local server, linking it to the account you just connected:

```bash
uv run python scripts/manage_unipile_webhook.py add --account-id <your_account_id>
```

Set `NGROK_DOMAIN` in `.env` first if you have a reserved ngrok domain, otherwise pass `--ngrok-domain`. See the script's docstring for the full add/update/remove/status usage.

### Turvo

Ask someone from the dev team for:
* sandbox access
* the partner API credentials (`client_id`, `client_secret`, `x_api_key`, `public_api_url`), these are shared across the whole team, not personal to you

Once you have the partner credentials, link your own Turvo login via `POST /api/user/turvo/authenticate`. The reason this is a separate step rather than just being handed a working config: Turvo access tokens expire in hours, not days, so a hardcoded token goes stale almost immediately. Linking properly gets you a `refresh_token` that keeps working on its own. Ask someone from the dev team whether they want you to use your own personal sandbox login or a shared test login for this, it depends how their Turvo sandbox seats are set up.

Once you're linked, the fastest way to see a real flow trigger is: grab a test shipment from your Turvo sandbox and manually change its status (e.g. to Covered, or Route Complete) to see the corresponding workflow fire against your local server.

### Test documents

Don't make up your own rate confirmation / POD PDFs, use the real examples the team already has: [Onboarding folder on SharePoint](https://freightx7.sharepoint.com/sites/Freightx-langraph_workflows/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FFreightx-langraph_workflows%2FShared%20Documents%2FOnboarding&viewid=6d9a38b7-efd6-4a39-a330-85bd77b4f33b&p=true&ga=1). Pick any ratecon/POD pair from there for the walkthrough below.

## Testing the t3ra workflows locally

Once you've connected Unipile and Turvo above (with ngrok already running), this walks through seeding the t3ra tenant and triggering the two flows we've verified working end to end locally: rate confirmation extraction, and driver assignment / POD collection.

### 1. Seed the t3ra tenant

```bash
uv run python scripts/apply_t3ra_tenant_settings_dev.py \
  --mikey-account-id <your_account_id> \
  --inbound-routing-email <the email you connected>
```

Add `--tms-*` flags if you already have the Turvo partner credentials, otherwise link Turvo afterward via `POST /api/user/turvo/authenticate`. See the script's docstring for details.

### 2. Register the Turvo webhook

Unlike Unipile, there's no script for this, Turvo webhooks are configured in Turvo's own UI (Settings, look for Public API / Webhooks). Add a row pointing at:

```
https://your-domain.ngrok-free.app/api/v1/webhook/turvo
```

Name it something identifiable as yours, and set it to Active. No auth header is needed, this route doesn't check one.

### 3. Trigger the ratecon flow

Pick a rate confirmation PDF from the SharePoint folder above. Note the shipment/load number in its filename, you'll need a matching test shipment in your Turvo sandbox for the later steps to resolve correctly.

Send a **fresh email** (not a reply) to the address you connected to Unipile, with:
- subject containing "rate confirmation" (case insensitive), and not containing "tonu" or "revised"
- the PDF attached

Watch the Celery worker log. You should see it resolve the shipment from Turvo and upload the attachment to S3 (`documents` table, `type=ratecon`). If nothing shows up in the log at all, check "Common issues" below, particularly the classification and S3 ones.

### 4. Trigger driver assignment / POD collection

This continues on the same email thread as the ratecon step above, it isn't a separate cold start. Do these in order:

- in Turvo, set the shipment status to Covered. This should trigger a driver assignment thread on the same email chain (a new email sent asking for driver details)
- reply to that email with any driver name/phone, this is what actually completes the driver assignment step
- once driver assignment is done, mark the shipment Route Complete in Turvo. This creates the POD `workflow_lifecycle` row and schedules reminder emails, it does not send one immediately, only on the reminder schedule
- pick a POD PDF from the SharePoint folder and **reply** (not a fresh email) on the same thread with it attached. This is what actually gets classified as `pod_lifecycle` and runs the extraction + scoring pipeline (scores the POD against Turvo shipment facts directly, see `scripts/pod-scoring-model-v2/`)

If you want to see a POD reminder email fire without waiting hours for the real schedule, you can revoke the scheduled Celery task and re-submit it with `countdown=0`, see `celery -A app.celery_app:celery_app inspect scheduled` to find it.

### 5. Re-run POD vs TMS scoring (stored S3 POD)

After a shipment already has a POD document in S3 (and ideally a `pod_extraction` row), you can re-score without re-uploading. Portal Bearer auth; jobs go to the tenant Celery work queue (`t3ra` for T3RA).

`POST /api/v1/shipments/rescore_pod_vs_tms`

- `shipment_ids`: `shipments.id` UUIDs (not Turvo shipment numbers), max 50
- `use_existing_extraction` (default `true`): reuse `document_analysis` `pod_extraction` when present; if missing, analyze the stored S3 PDF then score. Set `false` to always re-analyze the stored PDF before scoring
- Always re-fetches Turvo, then upserts `pod_vs_tms_analysis`
- One Celery task per shipment via `apply_async_on_work_queue`

```bash
curl -X POST "http://127.0.0.1:8000/api/v1/shipments/rescore_pod_vs_tms" \
  -H "Authorization: Bearer YOUR_PORTAL_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "shipment_ids": [
      "11111111-1111-1111-1111-111111111111"
    ],
    "use_existing_extraction": true
  }'
```

Optional header: `X-Tenant-Slug: t3ra` (must match the token tenant). Response is `202` with per-id `status` (`queued`, `not_found`, `no_pod_document`, …) and `celery_task_id`. Watch the T3RA worker log for `process_pod_vs_tms_rescore`. Restart the worker after pulling this endpoint so the task is registered.

## Common issues that you may run into

### `SignatureDoesNotMatch` or `InvalidAccessKeyId` on S3 upload

Check `BUCKET_ENDPOINT`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY` in `.env` all point at the local MinIO service together (`http://localhost:9002`, `minioadmin`, `minioadmin`), not a mix of local endpoint with real AWS creds or vice versa. Restart the Celery worker and `uvicorn` after changing `.env`, they only read it at startup.

### "no workflow classified" for every email you send

Most likely your test email isn't a fresh compose when it needs to be, or is a reply when it needs to be fresh. Rate confirmation classification requires `is_in_reply_to=False` (subject match, PDF attachment). POD classification requires `is_in_reply_to=True` (an actual Reply on the existing thread). Check `app/domain/t3ra/email_classification.py` for the exact rule if you're unsure.

### Route Complete webhook does nothing

`listen_turvo_status` requires an existing `ratecon` `workflow_lifecycle` for that shipment before it does anything with a Route Complete event, check the log for "no ratecon workflow_lifecycle for shipment_number". This means step 3 (the ratecon email) needs to have actually completed first, Route Complete alone doesn't start anything from scratch.

### `LangSmith pull_prompt failed ... 403 Forbidden` warnings in the log

Harmless if you don't have LangSmith Hub access, the code falls back to the local JSON files in `prompts/fallbacks/` automatically. If you want this to stop logging entirely, blank `LANGSMITH_API_KEY` and set `LANGSMITH_TRACING=false` in `.env`.

### Migration doesn't create any tenant

The identity_rbac migration in `freightx-api` only seeds a `gelita` tenant. There's no `t3ra` row until you run `apply_t3ra_tenant_settings_dev.py` (step 1 above).

### Port conflicts on 5432 / 6379 / 9000-9001

If you already run Postgres/Redis locally via Homebrew, stop them first: `brew services stop postgresql@14 redis`. MinIO's ports are remapped to 9002/9003 specifically because 9000/9001 are commonly already taken (Docker Desktop's own listeners on macOS, or another project's MinIO instance), check `docker ps` if you're not sure what's already running on those ports.

## Reference

### Run in LangGraph Studio

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

### Business DB migrations (Alembic)

```bash
uv run alembic upgrade head
```

Create a new revision:

```bash
uv run alembic revision -m "your migration message"
```

Note: LangGraph checkpoint tables are still managed by `PostgresSaver.setup()` at runtime. Alembic here is for app/business tables.

### Test POD_LIFECYCLE E2E

```bash
uv run pytest -c tests/pytest.ini \
  tests/e2e/scenarios/test_ratecon_workflow.py::test_ratecon_email_received_unipile_webhook \
  tests/e2e/scenarios/test_pod_lifecycle_route_complete_workflow.py::test_pod_lifecycle_route_complete_turvo_webhook \
  tests/e2e/scenarios/test_pod_lifecycle_email_received_workflow.py::test_pod_lifecycle_email_received_unipile_webhook \
  -v
```
