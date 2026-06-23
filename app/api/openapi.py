"""OpenAPI tag metadata for Swagger UI grouping."""

OPENAPI_TAGS: list[dict[str, str]] = [
    {"name": "health"},
    {"name": "webhooks", "description": "Inbound provider webhooks."},
    {"name": "turvo", "description": "Turvo account linking."},
    {"name": "shipments", "description": "Shipment operations."},
    {"name": "workflow-lifecycles", "description": "Workflow review actions."},
]
