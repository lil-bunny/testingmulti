from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
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

    DOCUMENTS_TABLE: str = "documents"
    DOCUMENT_ANALYSIS_TABLE: str = "document_analysis"
    # Fractional hours supported (e.g. 30s ≈ 0.00833333). Integers in .env still parse (24 → 24.0).
    REMINDER_0_HOURS:float = 0           # immediate
    REMINDER_1_HOURS:float = 0.01666666  # 1m later
    REMINDER_2_HOURS:float = 0.03333332  # 2m later
    POD_REMINDER_EMAIL_BODY: str = "Please send pod"
    # After nominal reminder time (ETA), Celery discards the task if not yet executed.
    REMINDER_EXPIRE_GRACE_HOURS: int = 2

    # Celery
    CELERY_BROKER_URL: str
    CELERY_RESULT_BACKEND: str

    # Unipile (required for POD reminder replies in thread)
    UNIPILE_API_KEY: str
    UNIPILE_BASE_URL: str = "https://api16.unipile.com:14674"
    UNIPILE_ACCOUNT_ID: str

    # Default workflow tenant when a webhook does not pass ?tenant_id= (must match app/configs/tenant_configs.py)
    STUDIO_TENANT_ID: str = "t3ra"
    TURVO_WEBHOOK_WORKFLOW_TENANT_ID: Optional[str] = None
    TENANTS_TABLE: str = "tenants"

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
    # Optional fallback app user id used by workflow tools when the workflow state does not carry one (e.g. Turvo webhook-triggered runs).
    # Turvo tokens + password: persisted under tenants.config (JSON), keyed by app_user_id
    TURVO_DEFAULT_APP_USER_ID: Optional[str] = "deb-test"

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
    UNIPILE_WEBHOOK_NAME: str = "pod_lifecycle_email_received_webhook"
    GELLITA_UNIPILE_ID: Optional[str] = "W7Xyw8gLT2mvog37VsGHZQ"
    GELLITA_TENANT_ID: str = "aadc75f4-3f79-45d7-84c3-aa778e226e93"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def DATABASE_URL(self) -> str:
        encoded_password = quote_plus(self.DATABASE_PASSWORD)
        return (
            f"postgresql://{self.DATABASE_USER}:{encoded_password}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )


settings = Settings()