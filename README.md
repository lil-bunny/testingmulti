# FreightX Agents

Python version: `3.11` (project baseline).

## Prerequisites

* [Docker](https://docs.docker.com/get-docker/)
* [uv](https://docs.astral.sh/uv/getting-started/installation/)
* [ngrok](https://ngrok.com/download), if you're testing Unipile/Turvo webhooks locally. Get a paid plan with a reserved/static domain if you can, a free rotating domain means re-registering your webhook URLs with Unipile and Turvo every time you restart the tunnel
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

- run the Celery worker (needed for anything that goes through the reminder scheduler or the async webhook ingest path, which is most of what you'll be testing):

```bash
uv run celery -A app.celery_app:celery_app worker --loglevel=info
```

On Windows, add `--pool=solo`.

## Secrets

`.env` holds real credentials. Never commit it, and follow the secrets policy in `CLAUDE.md`/`.cursor/rules/secrets-policy.mdc`, don't read/print its contents through an AI assistant either.

None of these are things you can generate yourself, ask someone from the dev team for all of them:

* `UNIPILE_API_KEY`, `UNIPILE_DSN`, `UNIPILE_WEBHOOK_SECRET`, needed for anything email related
* `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL`, the vision LLM used for POD/ratecon document extraction (the "agentic-turbo" service mentioned in `POD.md`). Nothing that touches a document will work without these
* Turvo sandbox access and partner API credentials, see below

`LANGSMITH_API_KEY` is optional. Local fallback prompts (`prompts/fallbacks/`) are used automatically if this is missing or doesn't have access to the prompt Hub, so the app works fine without it. If you want working traces/prompt pulls, you need to be invited into the team's LangSmith organization, a personal LangSmith signup won't have access to the team's prompts.

### Turvo

Ask someone from the dev team for:
* sandbox access
* the partner API credentials (`client_id`, `client_secret`, `x_api_key`, `public_api_url`), these are shared across the whole team, not personal to you

Once you have the partner credentials, link your own Turvo login via `POST /api/user/turvo/authenticate`. The reason this is a separate step rather than just being handed a working config: Turvo access tokens expire in hours, not days, so a hardcoded token goes stale almost immediately. Linking properly gets you a `refresh_token` that keeps working on its own. Ask someone from the dev team whether they want you to use your own personal sandbox login or a shared test login for this, it depends how their Turvo sandbox seats are set up.

Once you're linked, the fastest way to see a real flow trigger is: grab a test shipment from your Turvo sandbox and manually change its status (e.g. to Covered, or Route Complete) to see the corresponding workflow fire against your local server.

### Test documents

Don't make up your own rate confirmation / POD PDFs, use the real examples the team already has: [Onboarding folder on SharePoint](https://freightx7.sharepoint.com/sites/Freightx-langraph_workflows/Shared%20Documents/Forms/AllItems.aspx?id=%2Fsites%2FFreightx-langraph_workflows%2FShared%20Documents%2FOnboarding&viewid=6d9a38b7-efd6-4a39-a330-85bd77b4f33b&p=true&ga=1). Pick any ratecon/POD pair from there for the walkthrough below.

## Testing the t3ra workflows locally

This walks through getting the two flows we've verified working end to end locally: rate confirmation extraction, and driver assignment / POD collection.

The short version of how this all fits together: Unipile watches an email inbox and calls our webhook when mail arrives there, Turvo is the TMS that tracks the shipment and calls our webhook when its status changes, and ngrok is just a tunnel so those two outside services can reach your laptop. None of this works until all three (Unipile account, Turvo sandbox, ngrok tunnel) point at the same running local server. The steps below set that up in order.

### 1. Connect your own Unipile account

Emails need to arrive at an inbox Unipile actually has access to, it can't see mail sent to an address it doesn't control. Connect your own Gmail (or any account) rather than reusing someone else's, this generates a one-time link you open in a browser to sign in and grant access:

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

Open the printed URL, sign in, grant access. Then find your new account id:

```bash
uv run python scripts/manage_unipile_webhook.py accounts
```

### 2. Point a webhook at your local server

```bash
uv run python scripts/manage_unipile_webhook.py add --account-id <your_account_id>
```

Set `NGROK_DOMAIN` in `.env` first if you have a reserved ngrok domain, otherwise pass `--ngrok-domain`. See the script's docstring for the full add/update/remove/status usage.

### 3. Seed the t3ra tenant

```bash
uv run python scripts/apply_t3ra_tenant_settings_dev.py \
  --mikey-account-id <your_account_id> \
  --inbound-routing-email <the email you connected>
```

Add `--tms-*` flags if you already have the Turvo partner credentials, otherwise link Turvo afterward via `POST /api/user/turvo/authenticate`. See the script's docstring for details.

### 4. Start ngrok

Keep this running in its own terminal for the rest of the walkthrough, everything below depends on it staying up:

```bash
ngrok http 8000 --domain=your-domain.ngrok-free.app
```

### 5. Register the Turvo webhook

Unlike Unipile, there's no script for this, Turvo webhooks are configured in Turvo's own UI (Settings, look for Public API / Webhooks). Add a row pointing at:

```
https://your-domain.ngrok-free.app/api/v1/webhook/turvo
```

Name it something identifiable as yours, and set it to Active. No auth header is needed, this route doesn't check one.

### 6. Trigger the ratecon flow

Pick a rate confirmation PDF from the SharePoint folder above. Note the shipment/load number in its filename, you'll need a matching test shipment in your Turvo sandbox for the later steps to resolve correctly.

Send a **fresh email** (not a reply) to the address you connected in step 1, with:
- subject containing "rate confirmation" (case insensitive), and not containing "tonu" or "revised"
- the PDF attached

Watch the Celery worker log. You should see it resolve the shipment from Turvo, upload the attachment, run vision extraction, and cache the result (`document_analysis` table, `analysis_type=ratecon_extraction`). If nothing shows up in the log at all, check "Common issues" below, particularly the classification and S3 ones.

### 7. Trigger driver assignment / POD collection

This continues on the same email thread as the ratecon step above, it isn't a separate cold start. Do these in order:

- in Turvo, set the shipment status to Covered. This should trigger a driver assignment thread on the same email chain (a new email sent asking for driver details)
- reply to that email with any driver name/phone, this is what actually completes the driver assignment step
- once driver assignment is done, mark the shipment Route Complete in Turvo. This creates the POD `workflow_lifecycle` row and schedules reminder emails, it does not send one immediately, only on the reminder schedule
- pick a POD PDF from the SharePoint folder and **reply** (not a fresh email) on the same thread with it attached. This is what actually gets classified as `pod_lifecycle` and runs the extraction + cross-validation pipeline

If you want to see a POD reminder email fire without waiting hours for the real schedule, you can revoke the scheduled Celery task and re-submit it with `countdown=0`, see `celery -A app.celery_app:celery_app inspect scheduled` to find it.

## Common issues

### `SignatureDoesNotMatch` or `InvalidAccessKeyId` on S3 upload

Check `BUCKET_ENDPOINT`, `AWS_ACCESS_KEY_ID`, and `AWS_SECRET_ACCESS_KEY` in `.env` all point at the local MinIO service together (`http://localhost:9002`, `minioadmin`, `minioadmin`), not a mix of local endpoint with real AWS creds or vice versa. Restart the Celery worker and `uvicorn` after changing `.env`, they only read it at startup.

### "no workflow classified" for every email you send

Most likely your test email isn't a fresh compose when it needs to be, or is a reply when it needs to be fresh. Rate confirmation classification requires `is_in_reply_to=False` (subject match, PDF attachment). POD classification requires `is_in_reply_to=True` (an actual Reply on the existing thread). Check `app/domain/t3ra/email_classification.py` for the exact rule if you're unsure.

### `load_ratecon_analysis: cache miss` when replying with a POD

The POD flow cross-validates against a cached ratecon extraction. If step 6 above (the ratecon email) never actually completed (check `documents`/`document_analysis` for a `ratecon` row on that shipment), the POD flow will short-circuit to `end` before running extraction. Send the ratecon email again once S3 is working.

### Route Complete webhook does nothing

`listen_turvo_status` requires an existing `ratecon` `workflow_lifecycle` for that shipment before it does anything with a Route Complete event, check the log for "no ratecon workflow_lifecycle for shipment_number". This means step 6 (the ratecon email) needs to have actually completed first, Route Complete alone doesn't start anything from scratch.

### `LangSmith pull_prompt failed ... 403 Forbidden` warnings in the log

Harmless if you don't have LangSmith Hub access, the code falls back to the local JSON files in `prompts/fallbacks/` automatically. If you want this to stop logging entirely, blank `LANGSMITH_API_KEY` and set `LANGSMITH_TRACING=false` in `.env`.

### Migration doesn't create any tenant

The identity_rbac migration in `freightx-api` only seeds a `gelita` tenant. There's no `t3ra` row until you run `apply_t3ra_tenant_settings_dev.py` (step 3 above).

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
