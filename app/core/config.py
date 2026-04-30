from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from urllib.parse import quote_plus


class Settings(BaseSettings):
    APP_NAME: str = "Freight AI Platform"
    ENV: str = "dev"

    # LLM / observability
    OPENAI_API_KEY: Optional[str] = None
    LANGSMITH_API_KEY: Optional[str] = None
    LANGSMITH_TRACING: bool = True
    LLM_MODEL: Optional[str] = None
    LLM_BASE_URL: Optional[str] = None
    LLM_API_KEY: Optional[str] = None

    # Pydantic Logfire (set LOGFIRE_TOKEN in .env to enable tracing)
    LOGFIRE_TOKEN: Optional[str] = None
    LOGFIRE_SERVICE_NAME: str = "freightx"

    # DB
    DATABASE_HOST: str
    DATABASE_PORT: int
    DATABASE_NAME: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    # Workflow correlation persistence
    WORKFLOW_CORRELATION_TABLE: str
    REMINDER_1_HOURS: int
    REMINDER_2_HOURS: int

    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # Default workflow tenant when a webhook does not pass ?tenant_id= (must match app/configs/tenant_configs.py)
    STUDIO_TENANT_ID: str = "t3ra"
    TURVO_WEBHOOK_WORKFLOW_TENANT_ID: Optional[str] = None

    # Turvo Public API OAuth (optional until Turvo is configured)
    TURVO_PUBLICAPI_URL: Optional[str] = None
    TURVO_PUBLICAPI_CLIENT_ID: Optional[str] = None
    TURVO_PUBLICAPI_CLIENT_SECRET: Optional[str] = None
    TURVO_X_API_KEY: Optional[str] = None
    TURVO_TENANT_REF: Optional[str] = None
    # Fernet key (urlsafe base64) for encrypting per-user Turvo password at rest; strongly recommended in production
    TURVO_OAUTH_ENCRYPTION_KEY: Optional[str] = None
    # Optional fallback app user id used by workflow tools when the workflow state
    # does not carry one (e.g. Turvo webhook-triggered runs).
    TURVO_DEFAULT_APP_USER_ID: Optional[str] = None

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def DATABASE_URL(self) -> str:
        encoded_password = quote_plus(self.DATABASE_PASSWORD)
        return (
            f"postgresql://{self.DATABASE_USER}:{encoded_password}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )


settings = Settings()