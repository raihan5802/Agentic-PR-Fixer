"""Application configuration via Pydantic Settings."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnvironment(StrEnum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class LLMProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class CheckpointBackend(StrEnum):
    MEMORY = "memory"
    SQLITE = "sqlite"
    REDIS = "redis"


class Settings(BaseSettings):
    """Centralized environment-backed configuration."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    app_host: str = "0.0.0.0"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # LLM
    llm_provider: LLMProvider = LLMProvider.OPENAI
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    llm_model: str = "gpt-4o"

    # GitHub
    github_token: SecretStr
    github_webhook_secret: SecretStr | None = None

    # Workflow
    max_retry_count: int = Field(default=3, ge=0, le=10)
    sandbox_timeout_seconds: int = Field(default=300, ge=30, le=3600)
    sandbox_image: str = "autopatch-sandbox:latest"

    # LangGraph checkpoint persistence
    checkpoint_backend: CheckpointBackend = CheckpointBackend.MEMORY
    checkpoint_db_url: str = "sqlite:///./data/checkpoints.db"
    redis_url: str = "redis://localhost:6379/0"

    # API resiliency
    api_retry_attempts: int = Field(default=5, ge=1, le=10)

    @field_validator("llm_model")
    @classmethod
    def strip_model_name(cls, value: str) -> str:
        return value.strip()

    @property
    def is_production(self) -> bool:
        return self.app_env == AppEnvironment.PRODUCTION

    def resolve_llm_api_key(self) -> SecretStr:
        if self.llm_provider == LLMProvider.OPENAI:
            if self.openai_api_key is None:
                raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
            return self.openai_api_key

        if self.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=anthropic")
        return self.anthropic_api_key


@lru_cache
def get_settings() -> Settings:
    """Return cached settings singleton."""
    return Settings()
