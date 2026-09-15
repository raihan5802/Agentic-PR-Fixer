"""Tests for application settings."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from autopatch_agent.config import LLMProvider, Settings


def test_settings_requires_github_token(monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_settings_openai_key_required_for_openai_provider(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="OPENAI_API_KEY"):
        settings.resolve_llm_api_key()


def test_settings_anthropic_key_required_for_anthropic_provider(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    settings = Settings(_env_file=None)
    with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
        settings.resolve_llm_api_key()


def test_settings_resolves_openai_key(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    settings = Settings(_env_file=None)
    assert settings.llm_provider == LLMProvider.OPENAI
    assert settings.resolve_llm_api_key().get_secret_value() == "sk-test"
