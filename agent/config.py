"""Configuration for replaceable model providers; secrets remain SecretStr values."""

from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    model_provider: Literal["offline", "deepseek", "qwen", "local"] = "offline"
    jev_enabled: bool = False
    jev_pass2_enabled: bool = True
    jev_api_key: SecretStr | None = None
    jev_base_url: str = "https://api.typesafe.ai"
    jev_model: str = "jev-1.13.0"
    jev_timeout_seconds: float = Field(default=2.0, gt=0, le=30)
    jev_intent_min_confidence: float = Field(default=0.80, ge=0, le=1)
    jev_expense_intent_min_confidence: float = Field(default=0.75, ge=0, le=1)
    jev_max_injection: float = Field(default=0.03, ge=0, le=1)
    jev_min_in_scope: float = Field(default=0.97, ge=0, le=1)
    jev_plan_review_min: float = Field(default=0.70, ge=0, le=1)
    privacy_broker_enabled: bool = False
    resolution_enabled: bool = False
    request_deadline_seconds: float = Field(default=8.0, gt=0, le=60)
    business_timezone: str = "Asia/Shanghai"
    expense_tracking_enabled: bool = False
    expense_labeling_jev_enabled: bool = False
    expense_chat_enabled: bool = False
    expense_capture_enabled: bool = False
    expense_capture_chat_enabled: bool = False
    default_expense_currency: Literal["CNY", "USD", "EUR"] = "CNY"
    agent_routing_mode: Literal["hybrid", "llm_only"] = "hybrid"
    model_timeout_seconds: float = Field(default=30.0, gt=0, le=300)
    model_max_retries: int = Field(default=2, ge=0, le=5)

    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-flash"

    qwen_api_key: SecretStr | None = None
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"

    local_model_base_url: str = "http://127.0.0.1:11434/v1"
    local_model_name: str | None = None
    local_model_api_key: SecretStr | None = None

    agent_development_user_id: UUID | None = None
    agent_api_token: SecretStr = SecretStr("development-agent-only")
    banking_base_url: str = "http://127.0.0.1:8000"
    banking_service_token: SecretStr = SecretStr("development-only")
    banking_labeling_token: SecretStr = SecretStr("development-labeling-only")
    agent_database_url: str = Field(
        default="postgresql+psycopg://banking:banking@127.0.0.1:5432/banking",
        validation_alias=AliasChoices("AGENT_DATABASE_URL", "DATABASE_URL"),
    )
    agent_checkpoint_database_url: str | None = None

    @field_validator("agent_development_user_id", mode="before")
    @classmethod
    def empty_uuid_as_none(cls, value: object) -> object:
        return None if value == "" else value


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
