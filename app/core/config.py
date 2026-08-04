from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from urllib.parse import quote_plus

from app.models.tenants import TenantSlug


class Settings(BaseSettings):
    APP_NAME: str = "Freight AI Platform"
    ENV: str = "dev"

    # LLM / observability
    LANGSMITH_API_KEY: Optional[str] = None
    LANGSMITH_PROMPT_OWNER: Optional[str] = None
    LANGSMITH_PROJECT: Optional[str] = None
    LANGSMITH_ENDPOINT: Optional[str] = "https://api.smith.langchain.com"
    LANGSMITH_TRACING: bool = True
    LANGSMITH_TRACING_V2: bool = True
    LLM_BASE_URL: str
    LLM_POD_LIFECYCLE_API_KEY: str
    LLM_DRIVER_ASSIGNMENT_API_KEY: str
    LLM_APPOINTMENT_SCHEDULING_API_KEY: str
    LLM_LOAD_TENDERING_API_KEY: str
    LLM_CHAT_MODEL: str = "text"
    LLM_VISION_MODEL: str = "doc_processing_low"
    LLM_PDF_MODEL: str = "doc_processing_high"
    LLM_REQUEST_TIMEOUT: float = 500.0 # seconds

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
    REDIS_URL: str
    DEFAULT_WORK_QUEUE: str = "celery"
    T3RA_WORK_QUEUE: str = "t3ra"

    # Default workflow tenant when a webhook does not pass ?tenant_id= (must match app/configs/tenant_configs.py)
    STUDIO_TENANT_SLUG: str = TenantSlug.T3RA

    # Turvo
    TURVO_X_API_KEY: Optional[str] = None
    TURVO_TENANT_REF: Optional[str] = None
    # Fernet key (urlsafe base64) for encrypting per-user Turvo password at rest; strongly recommended in production
    TURVO_OAUTH_ENCRYPTION_KEY: Optional[str] = None
    # Optional fallback tenant slug for Turvo link/status API and local scripts when header is omitted.
    # Turvo tokens + password: in tenants.settings (JSON); row match uses tenants.slug.
    TURVO_DEFAULT_TENANT_SLUG: Optional[str] = Field(
        default=TenantSlug.T3RA,
        validation_alias=AliasChoices(
            "TURVO_DEFAULT_TENANT_SLUG",
            "TURVO_DEFAULT_APP_USER_ID",
        ),
    )
    # Turvo POST /documents payload limit (sandbox returns 413 above 10 MB).
    TURVO_POD_UPLOAD_MAX_BYTES: int = 10 * 1024 * 1024
    TURVO_POD_UPLOAD_TIMEOUT_S: float = 180.0
    TURVO_POD_UPLOAD_MAX_ATTEMPTS: int = 3
    TURVO_HTTP_MAX_ATTEMPTS: int = 5  # 1 initial try + 4 retries
    TURVO_HTTP_RETRY_DELAY_S: float = 15.0
    TURVO_POD_OPTIMIZE_DPI: int = 150
    TURVO_POD_OPTIMIZE_JPEG_QUALITY: int = 75
    TURVO_POD_OPTIMIZE_MAX_SIDE_PX: int = 1200

    # POD rasterization (pdf → JPEG; shared by ratecon text extraction + pod_optimizer)
    POD_MAX_IMAGE_PIXELS: int = 89_478_485
    POD_IMAGE_DPI: int = 150
    POD_JPEG_QUALITY: int = 80
    POD_IMAGE_MAX_SIDE_PX: int = 1200
    POD_PDF_THREAD_COUNT: int = 1
    POD_CONVERT_MAX_PAGE_BYTES: int = 80_000_000
    POD_CONVERT_MAX_TOTAL_BYTES: int = 400_000_000
    ATTACHMENT_CLASSIFIER_CONCURRENCY: int = 5

    # POD analysis (direct-PDF LLM call); fail closed above these before sending.
    POD_PDF_MAX_BYTES: int = 52_428_800  # 50 MiB
    POD_PDF_MAX_PAGES: int = 1000

    # OCR / native-text acquisition (shared by ratecon text path + POD strip)
    OCR_DPI: int = 120
    OCR_JPEG_QUALITY: int = 70
    OCR_IMAGE_MAX_SIDE_PX: int = 1600
    OCR_HEADER_FRACTION: float = 0.25
    OCR_NATIVE_TEXT_MIN_CHARS: int = 40
    # Parallel page OCR: each worker renders + OCRs (bound peak RSS).
    OCR_MAX_WORKERS: int = 2
    # Strip / header-only path (cheaper than full-page ratecon OCR).
    OCR_STRIP_DPI: int = 90
    OCR_STRIP_IMAGE_MAX_SIDE_PX: int = 1000
    # ONNX Runtime: app owns concurrency; keep per-inference ORT threads at 1.
    OCR_INTRA_OP_THREADS: int = 1

    # Unipile
    UNIPILE_API_KEY: str
    UNIPILE_DSN: str
    OAUTH_REDIRECT_URI: Optional[str] = None

    # S3-compatible Bucket (AWS S3)
    BUCKET_ENDPOINT: Optional[str] = None
    AWS_ACCESS_KEY_ID: str
    AWS_SECRET_ACCESS_KEY: str
    BUCKET_NAME: str
    BUCKET_REGION: str = "us-west-2"
    BUCKET_PRESIGN_EXPIRES_SECONDS: int = 600 # Presigned GetObject TTL (seconds)
    BUCKET_RATECON_ATTACHMENTS_FOLDER: str = "ratecon_attachments"
    BUCKET_POD_ATTACHMENTS_FOLDER: str = "pod_attachments"
    POD_ATTACHMENT_STAGE_ROOT: str = "/tmp/freightx/pod_staging"
    RATECON_STAGE_ROOT: str = "/tmp/freightx/ratecon_staging"

    # Webhooks
    UNIPILE_WEBHOOK_SECRET: str

    # freightx-api (portal auth delegation)
    FREIGHTX_API_BASE_URL: str = "http://localhost:8001"
    FREIGHTX_API_TIMEOUT_S: float = 10.0

    CORS_ALLOW_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

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
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]

    @property
    def sqlalchemy_database_url(self) -> str:
        """SQLAlchemy engine URL (psycopg v3 driver)."""
        encoded_password = quote_plus(self.DATABASE_PASSWORD)
        return (
            f"postgresql+psycopg://{self.DATABASE_USER}:{encoded_password}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )


settings = Settings()
