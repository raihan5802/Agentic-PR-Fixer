"""Tests for configurable LangGraph checkpoint backends."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver

from autopatch_agent.config import CheckpointBackend, Settings
from autopatch_agent.graph import build_checkpointer


def test_build_checkpointer_memory():
    settings = Settings(
        _env_file=None,
        github_token="ghp_test",
        checkpoint_backend=CheckpointBackend.MEMORY,
    )
    checkpointer = build_checkpointer(settings)
    assert isinstance(checkpointer, MemorySaver)


def test_build_checkpointer_sqlite(tmp_path):
    db_path = tmp_path / "checkpoints.db"
    settings = Settings(
        _env_file=None,
        github_token="ghp_test",
        checkpoint_backend=CheckpointBackend.SQLITE,
        checkpoint_db_url=f"sqlite:///{db_path}",
    )
    checkpointer = build_checkpointer(settings)
    assert checkpointer is not None
    assert type(checkpointer).__name__ == "SqliteSaver"


@patch("langgraph.checkpoint.redis.RedisSaver")
def test_build_checkpointer_redis(mock_redis_saver):
    mock_checkpointer = MagicMock()
    mock_context = MagicMock()
    mock_context.__enter__.return_value = mock_checkpointer
    mock_redis_saver.from_conn_string.return_value = mock_context
    settings = Settings(
        _env_file=None,
        github_token="ghp_test",
        checkpoint_backend=CheckpointBackend.REDIS,
        redis_url="redis://localhost:6379/0",
    )
    checkpointer = build_checkpointer(settings)
    mock_redis_saver.from_conn_string.assert_called_once_with("redis://localhost:6379/0")
    assert checkpointer is mock_checkpointer
