"""Configuration for replaceable model providers; secrets remain SecretStr values."""

from functools import lru_cache
from typing import Literal
from uuid import UUID

from pydantic import AliasChoices, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    model_provider: Literal["offline", "deepseek", "qwen", "local"] = "offline"
    agent_routing_mode: Literal["hybrid", "llm_only"] = "llm_only"
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
    agent_database_url: str = Field(
        default="postgresql+psycopg://banking:banking@localhost:5432/banking",
        validation_alias=AliasChoices("AGENT_DATABASE_URL", "DATABASE_URL"),
    )
    agent_checkpoint_database_url: str | None = None


@lru_cache
def get_agent_settings() -> AgentSettings:
    return AgentSettings()
