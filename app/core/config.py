from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional
from urllib.parse import quote_plus
import os


class Settings(BaseSettings):
    APP_NAME: str = "Freight AI Platform"
    ENV: str = "dev"

    # LLM / observability
    OPENAI_API_KEY: Optional[str] = None
    LANGSMITH_API_KEY: Optional[str] = None
    LANGSMITH_PROJECT: Optional[str] = None
    LANGSMITH_ENDPOINT: Optional[str] = "https://api.smith.langchain.com"
    LANGSMITH_TRACING: bool = True
    LANGSMITH_TRACING_V2: bool = True
    LLM_MODEL: Optional[str] = None
    LLM_BASE_URL: Optional[str] = None
    LLM_API_KEY: Optional[str] = None

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

    # Turvo
    TURVO_APP_URL: str = "https://app.turvo.com"
    TURVO_PUBLICAPI_URL:str = "https://publicapi.turvo.com"
    TURVO_PUBLICAPI_CLIENT_ID: str = "publicapi"
    TURVO_PUBLICAPI_CLIENT_SECRET: str = "secret"
    TURVO_USERNAME: str
    TURVO_PASSWORD: str
    TURVO_X_API_KEY: str

    # Unipile
    UNIPILE_API_KEY: str
    UNIPILE_DSN: str
    OAUTH_REDIRECT_URI: str

    # S3-compatible Bucket (AWS S3)
    DO_BUCKET_ENDPOINT: str = ""
    DO_BUCKET_ID: str = ""
    DO_BUCKET_KEY: str = ""
    BUCKET_NAME: str = ""
    BUCKET_REGION: str = "us-west-2"

    # Webhooks
    UNIPILE_WEBHOOK_SECRET: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def DATABASE_URL(self) -> str:
        encoded_password = quote_plus(self.DATABASE_PASSWORD)
        return (
            f"postgresql://{self.DATABASE_USER}:{encoded_password}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )


settings = Settings()