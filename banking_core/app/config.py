from functools import lru_cache
from uuid import UUID

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = Field(default="postgresql+psycopg://banking:banking@localhost:5432/banking")
    sql_echo: bool = False
    development_user_id: UUID | None = None
    mock_mfa_code: SecretStr | None = None
    banking_service_token: SecretStr = SecretStr("development-only")
    labeling_service_token: SecretStr = SecretStr("development-labeling-only")
    labeling_service_user_id: UUID | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
