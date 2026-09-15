"""Tests for API retry resiliency."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from github import GithubException, RateLimitExceededException

from autopatch_agent.resilience.retry import is_retryable_api_error


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, True),
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (401, False),
        (404, False),
    ],
)
def test_is_retryable_github_http_status(status, expected):
    request = MagicMock()
    headers = {}
    data = {}
    exc = GithubException(status, data, headers, request)
    assert is_retryable_api_error(exc) is expected


def test_is_retryable_github_rate_limit_exception():
    request = MagicMock()
    headers = {}
    data = {}
    exc = RateLimitExceededException(403, data, headers, request)
    assert is_retryable_api_error(exc) is True


def test_is_retryable_llm_rate_limit_by_status_code():
    exc = Exception("rate limited")
    exc.status_code = 429  # type: ignore[attr-defined]
    assert is_retryable_api_error(exc) is True


def test_is_retryable_llm_rate_limit_by_exception_name():
    class MockRateLimitError(Exception):
        pass

    assert is_retryable_api_error(MockRateLimitError("slow down")) is True


@patch("autopatch_agent.services.github._github_client")
def test_github_fetch_retries_on_rate_limit(mock_client_factory):
    from autopatch_agent.services.github import fetch_pull_request_files

    request = MagicMock()
    rate_limit = RateLimitExceededException(403, {}, {}, request)
    success_file = MagicMock(
        filename="a.py",
        patch="diff",
        status="modified",
        additions=1,
        deletions=0,
    )
    mock_pull = MagicMock()
    mock_pull.get_files.return_value = [success_file]
    mock_repo = MagicMock()
    mock_repo.get_pull.return_value = mock_pull
    mock_client = MagicMock()
    mock_client.get_repo.side_effect = [rate_limit, mock_repo]
    mock_client_factory.return_value = mock_client

    result = fetch_pull_request_files("org/repo", 1)

    assert len(result) == 1
    assert result[0]["path"] == "a.py"
    assert mock_client.get_repo.call_count == 2


@patch("autopatch_agent.nodes.generate_patch._build_llm")
def test_llm_invoke_retries_on_server_error(mock_build_llm):
    from autopatch_agent.nodes.generate_patch import PatchOutput, _invoke_patch_llm

    class ServerError(Exception):
        status_code = 503

    mock_llm = MagicMock()
    mock_llm.invoke.side_effect = [
        ServerError("upstream unavailable"),
        PatchOutput(patch_diff="diff", explanation="fixed"),
    ]
    mock_build_llm.return_value = mock_llm

    output = _invoke_patch_llm(mock_llm, "prompt")

    assert output.patch_diff == "diff"
    assert mock_llm.invoke.call_count == 2
