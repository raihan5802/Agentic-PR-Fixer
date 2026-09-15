"""Tests for patch generation node."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from autopatch_agent.nodes.generate_patch import (
    PatchOutput,
    build_patch_prompt,
    generate_patch,
)
from autopatch_agent.state import AgentState


def test_build_patch_prompt_includes_self_correction_on_retry():
    state: AgentState = {
        "repo_name": "org/repo",
        "pr_id": 42,
        "retry_count": 2,
        "lint_errors": [{"file": "a.py", "message": "E501 line too long"}],
        "file_changes": [{"path": "a.py", "patch": "..."}],
        "test_results": {
            "passed": False,
            "stdout": "1 failed",
            "stderr": "AssertionError",
            "exit_code": 1,
        },
    }

    prompt = build_patch_prompt(state)

    assert "SELF-CORRECTION" in prompt
    assert "attempt #2" in prompt
    assert "AssertionError" in prompt
    assert "1 failed" in prompt
    assert "E501 line too long" in prompt


def test_build_patch_prompt_omits_self_correction_on_first_attempt():
    state: AgentState = {
        "repo_name": "org/repo",
        "pr_id": 42,
        "retry_count": 0,
        "lint_errors": [],
        "file_changes": [],
    }

    prompt = build_patch_prompt(state)

    assert "SELF-CORRECTION" not in prompt


def test_generate_patch_returns_structured_output():
    state: AgentState = {
        "repo_name": "org/repo",
        "pr_id": 7,
        "retry_count": 0,
        "lint_errors": [],
        "file_changes": [],
    }

    mock_llm = MagicMock()
    mock_llm.with_structured_output.return_value.invoke.return_value = PatchOutput(
        patch_diff="diff --git a/foo.py b/foo.py\n",
        explanation="Fixed lint issue",
    )

    with patch("autopatch_agent.nodes.generate_patch._build_llm", return_value=mock_llm):
        result = generate_patch(state)

    assert result["generated_patch"] == "diff --git a/foo.py b/foo.py\n"
    assert result["patch_explanation"] == "Fixed lint issue"
    assert result["status"] == "sandbox_running"
