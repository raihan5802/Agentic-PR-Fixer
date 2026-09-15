"""Tests for LangGraph conditional routing."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from autopatch_agent.edges import (
    route_after_human_review,
    route_after_lint,
    should_retry_or_approve,
)
from autopatch_agent.state import AgentState


@pytest.mark.parametrize(
    ("lint_errors", "expected"),
    [
        ([{"file": "a.py", "message": "error"}], "generate_patch"),
        ([], "execute_sandbox"),
    ],
)
def test_route_after_lint(lint_errors, expected):
    state: AgentState = {"lint_errors": lint_errors}
    assert route_after_lint(state) == expected


@pytest.mark.parametrize(
    ("passed", "retry_count", "max_retries", "expected"),
    [
        (True, 0, 3, "human_review"),
        (True, 2, 3, "human_review"),
        (False, 0, 3, "generate_patch"),
        (False, 1, 3, "generate_patch"),
        (False, 2, 3, "generate_patch"),
        (False, 3, 3, "escalate_fallback"),
        (False, 5, 3, "escalate_fallback"),
    ],
)
def test_should_retry_or_approve(passed, retry_count, max_retries, expected):
    state: AgentState = {
        "test_results": {"passed": passed, "stdout": "", "stderr": ""},
        "retry_count": retry_count,
    }
    with patch("autopatch_agent.edges.get_settings") as mock_settings:
        mock_settings.return_value.max_retry_count = max_retries
        assert should_retry_or_approve(state) == expected


@pytest.mark.parametrize(
    ("human_approved", "expected"),
    [
        (True, "__end__"),
        (False, "__end__"),
        (None, "human_review"),
    ],
)
def test_route_after_human_review(human_approved, expected):
    state: AgentState = {"human_approved": human_approved}
    assert route_after_human_review(state) == expected
