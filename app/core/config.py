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

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def DATABASE_URL(self) -> str:
        encoded_password = quote_plus(self.DATABASE_PASSWORD)
        return (
            f"postgresql://{self.DATABASE_USER}:{encoded_password}"
            f"@{self.DATABASE_HOST}:{self.DATABASE_PORT}/{self.DATABASE_NAME}"
        )


settings = Settings()