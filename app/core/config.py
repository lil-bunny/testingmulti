from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote_plus
import os


class Settings(BaseSettings):
    APP_NAME: str = "Freight AI Platform"
    ENV: str = "dev"

    # LLM / observability
    LOGFIRE_TOKEN: Optional[str] = None
    LOGFIRE_SERVICE_NAME: Optional[str] = "freightx-local"
    OPENAI_API_KEY: Optional[str] = None
    LANGSMITH_API_KEY: Optional[str] = None
    LANGSMITH_PROMPT_OWNER: Optional[str] = None
    LANGSMITH_PROJECT: Optional[str] = None
    LANGSMITH_ENDPOINT: Optional[str] = "https://api.smith.langchain.com"
    LANGSMITH_TRACING: bool = True
    LANGSMITH_TRACING_V2: bool = True
    LLM_MODEL: Optional[str] = None
    LLM_BASE_URL: Optional[str] = None
    LLM_API_KEY: Optional[str] = None


    ATTACHMENT_CLASSIFIER_MODEL: Optional[str] = None
    # DB
    DATABASE_HOST: str
    DATABASE_PORT: int
    DATABASE_NAME: str
    DATABASE_USER: str
    DATABASE_PASSWORD: str

    # Platform cap for Celery Redis visibility_timeout (tenant delay_hours must stay below this).
    MAX_REMINDER_DELAY_HOURS: float = 72.0
    REMINDER_EXPIRE_GRACE_HOURS: int = 2

    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # Unipile (required for POD reminder replies in thread)
    UNIPILE_API_KEY: str
    UNIPILE_BASE_URL: str = "https://api16.unipile.com:14674"
    UNIPILE_ACCOUNT_ID: str

    # Default workflow tenant when a webhook does not pass ?tenant_id= (must match app/configs/tenant_configs.py)
    STUDIO_TENANT_SLUG: str = "t3ra"
    TURVO_WEBHOOK_WORKFLOW_TENANT_ID: Optional[str] = None

    # Turvo
    TURVO_APP_URL: str = "https://app.turvo.com"
    TURVO_PUBLICAPI_URL:str = "https://publicapi.turvo.com"
    TURVO_PUBLICAPI_CLIENT_ID: str = "publicapi"
    TURVO_PUBLICAPI_CLIENT_SECRET: str = "secret"
    TURVO_USERNAME: str
    TURVO_PASSWORD: str
    TURVO_X_API_KEY: str
    TURVO_TENANT_REF: Optional[str] = None
    # Fernet key (urlsafe base64) for encrypting per-user Turvo password at rest; strongly recommended in production
    TURVO_OAUTH_ENCRYPTION_KEY: Optional[str] = None
    # Optional fallback tenant slug for Turvo link/status API and local scripts when header is omitted.
    # Turvo tokens + password: in tenants.settings (JSON); row match uses tenants.slug.
    TURVO_DEFAULT_TENANT_SLUG: Optional[str] = Field(
        default="t3ra",
        validation_alias=AliasChoices(
            "TURVO_DEFAULT_TENANT_SLUG",
            "TURVO_DEFAULT_APP_USER_ID",
        ),
    )

    # Unipile
    UNIPILE_API_KEY: str
    UNIPILE_DSN: str
    OAUTH_REDIRECT_URI: str

    # S3-compatible Bucket (AWS S3)
    BUCKET_ENDPOINT: str
    BUCKET_ID: str
    BUCKET_KEY: str
    BUCKET_NAME: str
    BUCKET_REGION: str = "us-west-2"
    BUCKET_PRESIGN_EXPIRES_SECONDS: int = 600 # Presigned GetObject TTL (seconds)
    BUCKET_RATECON_ATTACHMENTS_FOLDER: str = "ratecon_attachments"
    BUCKET_POD_ATTACHMENTS_FOLDER: str = "pod_attachments" # also default folder for all uploads if not provided in args of S3 service

    # Webhooks
    UNIPILE_WEBHOOK_SECRET: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

#   for langgraph checkpointer
    @property
    def DATABASE_URL(self) -> str:
        encoded_password = quote_plus(self.DATABASE_PASSWORD)
        return (
            f"postgresql://{self.DATABASE_USER}:{encoded_password}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )

    # for SQLAlchemy engine URL (psycopg v3 driver)
    @property
    def sqlalchemy_database_url(self) -> str:
        """SQLAlchemy engine URL (psycopg v3 driver)."""
        encoded_password = quote_plus(self.DATABASE_PASSWORD)
        return (
            f"postgresql+psycopg://{self.DATABASE_USER}:{encoded_password}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )


settings = Settings()