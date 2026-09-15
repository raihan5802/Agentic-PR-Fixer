"""Tests for DockerSandboxRunner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import docker
import pytest
from requests.exceptions import ReadTimeout

from autopatch_agent.sandbox import (
    DockerDaemonError,
    DockerSandboxRunner,
    SandboxTimeoutError,
    run_tests_with_patch,
)


@pytest.fixture
def mock_container():
    container = MagicMock()
    container.wait.return_value = {"StatusCode": 0}
    container.attrs = {"State": {"ExitCode": 0}}
    container.logs.side_effect = lambda stdout=True, stderr=False: (
        b"tests ok\n" if stdout else b""
    )
    return container


@pytest.fixture
def mock_docker_client(mock_container):
    client = MagicMock()
    client.ping.return_value = True
    client.containers.run.return_value = mock_container
    return client


def test_run_tests_with_patch_success(mock_docker_client, mock_container, tmp_path):
    runner = DockerSandboxRunner(client=mock_docker_client, timeout_seconds=30)

    with patch.object(runner, "_clone_repository", return_value=tmp_path / "repo"):
        result = runner.run_tests_with_patch(
            "https://github.com/org/repo.git",
            "diff --git a/foo.py b/foo.py\n",
        )

    assert result["passed"] is True
    assert result["exit_code"] == 0
    assert result["stdout"] == "tests ok\n"
    assert "error" not in result
    mock_container.wait.assert_called_once_with(timeout=30)
    mock_container.remove.assert_called_once_with(force=True)


def test_run_tests_with_patch_empty_patch(mock_docker_client):
    runner = DockerSandboxRunner(client=mock_docker_client)
    result = runner.run_tests_with_patch("https://github.com/org/repo.git", "  ")

    assert result["passed"] is False
    assert result["error"] == "patch_diff is empty"
    mock_docker_client.containers.run.assert_not_called()


def test_run_tests_with_patch_docker_daemon_unavailable():
    client = MagicMock()
    client.ping.side_effect = docker.errors.DockerException("connection refused")

    runner = DockerSandboxRunner(client=client)
    with patch.object(runner, "_clone_repository"):
        result = runner.run_tests_with_patch(
            "https://github.com/org/repo.git",
            "diff --git a/foo.py b/foo.py\n",
        )

    assert result["passed"] is False
    assert result["error"] == "docker_daemon_unavailable"


def test_run_tests_with_patch_execution_timeout(mock_docker_client, mock_container, tmp_path):
    mock_container.wait.side_effect = ReadTimeout("timed out")
    runner = DockerSandboxRunner(client=mock_docker_client, timeout_seconds=30)

    with patch.object(runner, "_clone_repository", return_value=tmp_path / "repo"):
        result = runner.run_tests_with_patch(
            "https://github.com/org/repo.git",
            "diff --git a/foo.py b/foo.py\n",
        )

    assert result["passed"] is False
    assert result["error"] == "execution_timeout"
    assert result["exit_code"] == 124
    mock_container.remove.assert_called_once_with(force=True)


def test_run_tests_with_patch_clone_failure(mock_docker_client):
    runner = DockerSandboxRunner(client=mock_docker_client)

    with patch.object(
        runner,
        "_clone_repository",
        side_effect=__import__("subprocess").CalledProcessError(
            128, "git clone", stderr="fatal: repo not found"
        ),
    ):
        result = runner.run_tests_with_patch(
            "https://github.com/org/missing.git",
            "diff --git a/foo.py b/foo.py\n",
        )

    assert result["passed"] is False
    assert result["error"] == "repository_clone_failed"
    mock_docker_client.containers.run.assert_not_called()


def test_spawn_container_uses_security_hardening(mock_docker_client, tmp_path):
    runner = DockerSandboxRunner(client=mock_docker_client)

    with patch.object(runner, "_clone_repository", return_value=tmp_path / "repo"):
        runner.run_tests_with_patch(
            "https://github.com/org/repo.git",
            "diff --git a/foo.py b/foo.py\n",
        )

    args, kwargs = mock_docker_client.containers.run.call_args
    assert args[0] == "python:3.11-slim"
    assert kwargs["network_disabled"] is True
    assert kwargs["cap_drop"] == ["ALL"]
    assert kwargs["mem_limit"] == "512m"


def test_client_property_raises_docker_daemon_error():
    runner = DockerSandboxRunner(client=None)
    with patch("autopatch_agent.sandbox.docker.from_env", side_effect=docker.errors.DockerException):
        with pytest.raises(DockerDaemonError):
            _ = runner.client


def test_module_level_run_tests_with_patch(mock_docker_client, tmp_path):
    with patch("autopatch_agent.sandbox.docker.from_env", return_value=mock_docker_client):
        with patch.object(
            DockerSandboxRunner,
            "_clone_repository",
            return_value=tmp_path / "repo",
        ):
            result = run_tests_with_patch(
                "https://github.com/org/repo.git",
                "diff --git a/foo.py b/foo.py\n",
            )

    assert result["passed"] is True


def test_sandbox_timeout_error_message():
    err = SandboxTimeoutError("boom")
    assert "boom" in str(err)
