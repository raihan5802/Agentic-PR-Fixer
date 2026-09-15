"""Docker container SDK runner for isolated patch validation."""

from __future__ import annotations

import logging
import shlex
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import docker
from docker.errors import APIError, DockerException, ImageNotFound, NotFound
from requests.exceptions import ReadTimeout

from autopatch_agent.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_IMAGE = "python:3.11-slim"
DEFAULT_EXECUTION_TIMEOUT_SECONDS = 30
WORKSPACE_MOUNT = "/workspace"
REPO_DIR = f"{WORKSPACE_MOUNT}/repo"
PATCH_PATH = f"{WORKSPACE_MOUNT}/patch.diff"

SandboxResult = dict[str, Any]


class DockerDaemonError(RuntimeError):
    """Raised when the Docker daemon is unreachable or misconfigured."""


class SandboxTimeoutError(TimeoutError):
    """Raised when sandbox execution exceeds the configured timeout."""


class DockerSandboxRunner:
    """
    Securely executes generated patches inside an ephemeral Docker container.

    The runner shallow-clones the target repository on the host into a temporary
    directory, mounts it into an isolated ``python:3.11-slim`` container, applies
    the patch with ``git apply``, and runs ``pytest`` followed by ``ruff check .``.
    """

    def __init__(
        self,
        client: docker.DockerClient | None = None,
        *,
        image: str = DEFAULT_IMAGE,
        timeout_seconds: int = DEFAULT_EXECUTION_TIMEOUT_SECONDS,
        mem_limit: str = "512m",
        cpu_quota: int = 100_000,
    ) -> None:
        self._image = image
        self._timeout_seconds = timeout_seconds
        self._mem_limit = mem_limit
        self._cpu_quota = cpu_quota
        self._client = client

    @property
    def client(self) -> docker.DockerClient:
        if self._client is None:
            try:
                self._client = docker.from_env()
                self._client.ping()
            except DockerException as exc:
                raise DockerDaemonError(
                    "Unable to connect to the Docker daemon. "
                    "Ensure Docker is running and accessible."
                ) from exc
        return self._client

    def run_tests_with_patch(self, repo_url: str, patch_diff: str) -> SandboxResult:
        """
        Clone a repository, apply a patch, and run validation commands in Docker.

        Returns a dict with keys: ``passed``, ``stdout``, ``stderr``, ``exit_code``,
        ``duration_seconds``, and ``error`` (when execution fails before tests complete).
        """
        start = time.monotonic()
        container = None

        if not patch_diff.strip():
            return self._result(
                passed=False,
                stdout="",
                stderr="",
                exit_code=1,
                duration_seconds=0.0,
                error="patch_diff is empty",
            )

        try:
            self._ensure_daemon()
            with tempfile.TemporaryDirectory(prefix="autopatch-sandbox-") as tmp:
                workspace = Path(tmp)
                self._clone_repository(repo_url, workspace / "repo")
                patch_file = workspace / "patch.diff"
                patch_file.write_text(patch_diff, encoding="utf-8")

                container = self._run_container(workspace)
                exit_code, stdout, stderr = self._collect_results(container)

                return self._result(
                    passed=exit_code == 0,
                    stdout=stdout,
                    stderr=stderr,
                    exit_code=exit_code,
                    duration_seconds=time.monotonic() - start,
                )

        except DockerDaemonError as exc:
            logger.error("Docker daemon error: %s", exc)
            return self._result(
                passed=False,
                stdout="",
                stderr=str(exc),
                exit_code=1,
                duration_seconds=time.monotonic() - start,
                error="docker_daemon_unavailable",
            )
        except SandboxTimeoutError as exc:
            logger.warning("Sandbox timed out for %s: %s", repo_url, exc)
            return self._result(
                passed=False,
                stdout="",
                stderr=str(exc),
                exit_code=124,
                duration_seconds=time.monotonic() - start,
                error="execution_timeout",
            )
        except DockerException as exc:
            logger.exception("Docker execution failed for %s", repo_url)
            return self._result(
                passed=False,
                stdout="",
                stderr=str(exc),
                exit_code=1,
                duration_seconds=time.monotonic() - start,
                error="docker_execution_failed",
            )
        except subprocess.CalledProcessError as exc:
            logger.error("Repository clone failed for %s: %s", repo_url, exc.stderr)
            return self._result(
                passed=False,
                stdout=exc.stdout or "",
                stderr=exc.stderr or str(exc),
                exit_code=exc.returncode,
                duration_seconds=time.monotonic() - start,
                error="repository_clone_failed",
            )
        finally:
            if container is not None:
                self._destroy_container(container)

    def _ensure_daemon(self) -> None:
        """Verify the Docker daemon is reachable before spawning containers."""
        try:
            self.client.ping()
        except DockerException as exc:
            raise DockerDaemonError(
                "Unable to connect to the Docker daemon. "
                "Ensure Docker is running and accessible."
            ) from exc

    def _clone_repository(self, repo_url: str, destination: Path) -> Path:
        """Shallow-clone the repository on the host with optional GitHub token auth."""
        clone_url = self._authenticated_repo_url(repo_url)
        destination.parent.mkdir(parents=True, exist_ok=True)

        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--single-branch",
                clone_url,
                str(destination),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=self._timeout_seconds,
        )
        return destination

    def _authenticated_repo_url(self, repo_url: str) -> str:
        """Inject GitHub token for private repository access when configured."""
        settings = get_settings()
        token = settings.github_token.get_secret_value()

        if repo_url.startswith("git@"):
            return repo_url

        parsed = urlparse(repo_url)
        if parsed.netloc in {"github.com", "www.github.com"}:
            return f"https://x-access-token:{token}@{parsed.netloc}{parsed.path}"

        return repo_url

    def _validation_script(self) -> str:
        """Shell script executed inside the container."""
        return f"""
set -eu
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends git > /dev/null
pip install --no-cache-dir -q pytest ruff
cd {shlex.quote(REPO_DIR)}
git apply --whitespace=fix {shlex.quote(PATCH_PATH)}
pytest -q
ruff check .
""".strip()

    def _run_container(self, workspace: Path):
        """Spawn an isolated container and block until validation completes or times out."""
        try:
            container = self.client.containers.run(
                self._image,
                command=["/bin/sh", "-c", self._validation_script()],
                detach=True,
                remove=False,
                working_dir=REPO_DIR,
                volumes={
                    str(workspace): {"bind": WORKSPACE_MOUNT, "mode": "rw"},
                },
                network_disabled=True,
                mem_limit=self._mem_limit,
                cpu_quota=self._cpu_quota,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                tmpfs={"/tmp": "size=64m,mode=1777"},
            )
        except ImageNotFound as exc:
            raise DockerException(
                f"Sandbox image '{self._image}' not found locally. "
                f"Pull it with: docker pull {self._image}"
            ) from exc
        except APIError as exc:
            raise DockerDaemonError(f"Failed to spawn sandbox container: {exc}") from exc

        try:
            container.wait(timeout=self._timeout_seconds)
        except ReadTimeout as exc:
            self._destroy_container(container)
            raise SandboxTimeoutError(
                f"Sandbox execution exceeded {self._timeout_seconds}s timeout"
            ) from exc

        return container

    def _collect_results(self, container) -> tuple[int, str, str]:
        """Read exit code and logs from a finished container."""
        state = container.attrs.get("State", {})
        exit_code = state.get("ExitCode", 1)
        stdout = container.logs(stdout=True, stderr=False).decode("utf-8", errors="replace")
        stderr = container.logs(stdout=False, stderr=True).decode("utf-8", errors="replace")
        return exit_code, stdout, stderr

    @staticmethod
    def _destroy_container(container) -> None:
        """Force-remove the container, swallowing cleanup errors."""
        try:
            container.kill()
        except (DockerException, NotFound):
            pass
        try:
            container.remove(force=True)
        except (DockerException, NotFound):
            logger.debug("Container already removed")

    @staticmethod
    def _result(
        *,
        passed: bool,
        stdout: str,
        stderr: str,
        exit_code: int,
        duration_seconds: float,
        error: str | None = None,
    ) -> SandboxResult:
        result: SandboxResult = {
            "passed": passed,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": exit_code,
            "duration_seconds": round(duration_seconds, 3),
        }
        if error is not None:
            result["error"] = error
        return result


def run_tests_with_patch(repo_url: str, patch_diff: str) -> SandboxResult:
    """Module-level convenience wrapper around :class:`DockerSandboxRunner`."""
    return DockerSandboxRunner().run_tests_with_patch(repo_url, patch_diff)


class SandboxRunner(DockerSandboxRunner):
    """Adapter for graph nodes that pass ``repo_name`` instead of a full URL."""

    def run(self, *, patch: str, repo_name: str) -> SandboxResult:
        repo_url = f"https://github.com/{repo_name}.git"
        return self.run_tests_with_patch(repo_url, patch)
