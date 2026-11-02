from decimal import Decimal
from functools import lru_cache
from uuid import UUID

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    database_url: str = Field(default="postgresql+psycopg://banking:banking@127.0.0.1:5432/banking")
    sql_echo: bool = False
    development_user_id: UUID | None = None
    mock_mfa_code: SecretStr | None = None
    banking_service_token: SecretStr = SecretStr("development-only")
    labeling_service_token: SecretStr = SecretStr("development-labeling-only")
    labeling_service_user_id: UUID | None = None
    # Annual interest rate given to new savings pots (0.015 = 1.5%). Existing pots keep theirs.
    savings_interest_rate: Decimal = Field(default=Decimal("0.0150"), ge=0, lt=1)

    @field_validator("labeling_service_user_id", "development_user_id", mode="before")
    @classmethod
    def empty_uuid_as_none(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_settings() -> Settings:
    return Settings()
