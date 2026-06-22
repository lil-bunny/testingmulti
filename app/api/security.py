"""OpenAPI security schemes (Swagger auth buttons)."""

from fastapi.security import HTTPBearer

portal_bearer = HTTPBearer(
    scheme_name="BearerAuth",
    description="Portal Bearer token.",
    auto_error=False,
)

unipile_webhook_bearer = HTTPBearer(
    scheme_name="WebhookBearer",
    description="Webhook Bearer token.",
    auto_error=False,
)
