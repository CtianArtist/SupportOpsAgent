from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven application settings."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    llm_provider: Literal["mock", "openai", "anthropic"] = "mock"
    model_name: str | None = None
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    database_url: str = Field(
        default="sqlite:///./supportops.db",
        validation_alias="SUPPORTOPS_DATABASE_URL",
    )
    max_agent_steps: int = Field(default=8, ge=1, le=20)
    tool_retry_attempts: int = Field(default=3, ge=1, le=5)
    retry_base_delay_seconds: float = Field(default=0.05, ge=0, le=10)
    llm_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    @property
    def resolved_model_name(self) -> str:
        if self.model_name:
            return self.model_name
        if self.llm_provider == "anthropic":
            return "claude-3-5-haiku-latest"
        return "gpt-4o-mini"


@lru_cache
def get_settings() -> Settings:
    return Settings()