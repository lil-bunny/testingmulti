# Load tendering: email webhook to database

How an inbound **mail** webhook (currently **Unipile**) becomes **stored tenders** backed by **`data_imports`** and Postgres **`tenants`**.

## Prerequisites

| Requirement | Detail |
|------------|--------|
| **HTTP auth** | `Authorization: Bearer <UNIPILE_WEBHOOK_SECRET>`. |
| **Tenant routing** | A row in **`tenants`** whose JSON **`settings.email_webhook_name`** equals **`payload.webhook_name`** exactly. If no row matches, the API responds with `{"message": "invalid webhook"}` **before** workflow classification. |
| **Classification** | **Load tendering** when **`webhook_name`** maps to a tenant **and** the email has **`has_attachments`**, **`attachments[].extension == xlsx`**, etc. (see `WorkflowClassifierService`). |
| **Ingest path** | Unipile bytes are fetched with **`email_id`**, **`account_id`**, **`attachment_id`** from the webhook (`build_unipile_attachment_fetch_context`). |

Operational note: configure the Unipile webhook so its **`webhook_name`** matches the value you store under **`email_webhook_name`** in **`tenants.settings`** (for example `"gelita"` on both sides).

## High-level sequence

Below, **solid lines** show the primary **load tendering** happy path after auth. Rate-con/POD mails still validate **tenant routing** first, then classify differently and may enqueue LangGraph (`run_workflow_async`) instead of inserting tenders.

```mermaid
sequenceDiagram
    participant U as Mail provider webhook
    participant API as POST /api/webhook/unipile
    participant R as resolve_email_data_import_tenant_id
    participant DBt as Postgres tenants
    participant C as WorkflowClassifierService
    participant Ing as Email attachment ingestion
    participant DIP as Email import projection
    participant TI as TendersIngestService
    participant DBi as Postgres data_imports / tenders

    U->>API: mail_received payload + Bearer
    API->>R: payload
    R->>DBt: lookup settings.email_webhook_name = webhook_name
    DBt-->>R: tenants.id
    alt no tenant row
        R-->>API: None
        API-->>U: invalid webhook
    end
    R-->>API: data_import_tenant_id
    API->>C: classify_workflow_type(payload)
    C-->>API: workflow_name (e.g. load_tendering)
    API->>Ing: process_email_webhook_attachment_import (excel path)
    Ing->>DBi: write data_imports row
    Ing-->>API: data_import_id
    alt load_tendering
        API->>DIP: load_email_data_import_projection
        DIP->>DBi: read + project spreadsheet rows
        DIP-->>API: array_of_tenders
        API->>TI: persist_tender_rows_from_email_import_projection
        TI->>DBi: insert tenders rows
        API-->>U: JSON success + data_import_id (no Celery)
    else ratecon / pod_lifecycle
        API-->>U: enqueue workflow (execution_id) optional data_import_id
    end
```

## Structural flowchart

Shows **decision gates** shared by every accepted mail webhook.

```mermaid
flowchart TD
    A["POST /api/webhook/unipile<br/>Bearer OK"] --> B["resolve_email_data_import_tenant_id"]
    B --> C{"tenant row for webhook_name?"}
    C -->|no| Z["{'message':'invalid webhook'}"]
    C -->|yes| D["WorkflowClassifierService"]
    D --> E{"workflow_name"}
    E -->|load_tendering| F["Excel ingest → data_imports"]
    F --> G["Projection → array_of_tenders"]
    G --> H["persist tenders"]
    H --> I["HTTP 200: success + data_import_id"]
    E -->|ratecon / pod| J["Optional same ingest if attachment"]
    J --> K["Celery run_workflow_async"]
    K --> L["HTTP 200: execution_id"]
```

## Code map

| Piece | Responsibility |
|-------|----------------|
| **`app/api/routes.py`** | Auth, **`resolve_email_data_import_tenant_id`**, classify, ingestion, projection + tenders for **`load_tendering`**, workflow queue for others. |
| **`app/services/data_import_tenant_resolution.py`** | Maps **`payload["webhook_name"]`** → **`tenants.id`**. |
| **`app/repositories/tenants_db_repository.py`** | SQL: **`settings::jsonb->>'email_webhook_name'`**. |
| **`app/services/workflow_classifier_service.py`** | **`load_tendering`** iff tenant mapping exists + `.xlsx` attachment rules. |
| **`app/services/email_webhook_attachment_ingestion.py`** | Fetch bytes, **`ingest_data`**, record **`data_imports`**. |
| **`app/services/email_import_projection.py`** | **`load_email_data_import_projection`**, **`persist_tender_rows_from_email_import_projection`** (wrapped in try/log). |
| **`app/services/data_imports_read_service.py`** | Parsed spreadsheet → **`get_projected_rows(..., projection=LOAD_TENDERING_ROW_PROJECTION)`**; call from code (workflows, scripts, tasks)—no dedicated HTTP route. |
| **`app/domain/*`** | Projection, tabular iteration, **`load_tendering_tender_rows`** mapping into DB shape. |
| **`app/repositories/tenders_repository.py`** | **`tenders` batch inserts**. |
| **Migrations** | **`20260513_01`** **`tenants`** · **`20260514_01`** **`data_imports`** · **`20260515_01`** **`tenders`** + enum. Head **`20260515_01`**. Run **`alembic upgrade head`**. |

## Reading projected rows (library reuse)

Reuse the service directly instead of REST:

```python
from app.configs.load_tendering_import_projection import LOAD_TENDERING_ROW_PROJECTION
from app.services.data_imports_read_service import DataImportsReadService

rows, meta = DataImportsReadService().get_projected_rows(
    tenant_id,
    data_import_id,
    projection=LOAD_TENDERING_ROW_PROJECTION,
)
# rows is None if no data_import for (tenant_id, id); else list[dict].
```

Ingest-facing code can use **`load_email_data_import_projection`** in **`app/services/email_import_projection.py`** (same projection, guarded I/O).

