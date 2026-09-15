"""Tests for sandbox execution node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from autopatch_agent.nodes.execute_sandbox import execute_sandbox
from autopatch_agent.state import AgentState


def test_execute_sandbox_success():
    state: AgentState = {
        "pr_id": 1,
        "repo_name": "org/repo",
        "generated_patch": "diff --git a/a.py b/a.py\n",
        "retry_count": 0,
    }
    mock_runner = MagicMock()
    mock_runner.run.return_value = {
        "passed": True,
        "stdout": "ok",
        "stderr": "",
        "exit_code": 0,
    }

    with patch("autopatch_agent.nodes.execute_sandbox.SandboxRunner", return_value=mock_runner):
        result = execute_sandbox(state)

    assert result["test_results"]["passed"] is True
    assert result["status"] == "awaiting_human_review"
    assert "retry_count" not in result
    mock_runner.run.assert_called_once_with(
        patch="diff --git a/a.py b/a.py\n",
        repo_name="org/repo",
    )


def test_execute_sandbox_failure_increments_retry_count():
    state: AgentState = {
        "pr_id": 1,
        "repo_name": "org/repo",
        "generated_patch": "diff --git a/a.py b/a.py\n",
        "retry_count": 1,
    }
    mock_runner = MagicMock()
    mock_runner.run.return_value = {
        "passed": False,
        "stdout": "",
        "stderr": "tests failed",
        "exit_code": 1,
    }

    with patch("autopatch_agent.nodes.execute_sandbox.SandboxRunner", return_value=mock_runner):
        result = execute_sandbox(state)

    assert result["test_results"]["passed"] is False
    assert result["retry_count"] == 1
    assert result["status"] == "generating_patch"
    assert result["error"] == "tests failed"


def test_execute_sandbox_missing_patch():
    result = execute_sandbox({"pr_id": 1, "repo_name": "org/repo"})
    assert result["status"] == "failed"
    assert "No generated patch" in result["error"]
