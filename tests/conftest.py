"""Shared pytest fixtures."""

from __future__ import annotations

from contextlib import ExitStack
from unittest.mock import patch

import pytest
from langgraph.checkpoint.memory import MemorySaver

from autopatch_agent.config import get_settings
from autopatch_agent.graph import get_compiled_graph, reset_compiled_graph


@pytest.fixture(autouse=True)
def _reset_settings():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def env_vars(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "test-webhook-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()


@pytest.fixture
def workflow_graph(env_vars):
    """Shared in-memory LangGraph instance for API tests."""
    reset_compiled_graph(checkpointer=MemorySaver())
    return get_compiled_graph()


@pytest.fixture
def client(env_vars, workflow_graph):
    from fastapi.testclient import TestClient

    from main import create_app

    with ExitStack() as stack:
        stack.enter_context(
            patch("autopatch_agent.api.routes.get_compiled_graph", return_value=workflow_graph)
        )
        with TestClient(create_app()) as test_client:
            test_client.app.state.graph = workflow_graph
            yield test_client
