"""Run static analysis (ruff) against changed files."""

from __future__ import annotations

import logging
import subprocess
import tempfile
from pathlib import Path

from autopatch_agent.state import AgentState, LintError

logger = logging.getLogger(__name__)


def _write_temp_files(file_changes: list) -> Path:
    root = Path(tempfile.mkdtemp(prefix="autopatch-lint-"))
    for change in file_changes:
        file_path = root / change["path"]
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # Write patch content placeholder; real impl would apply patches
        file_path.write_text(change.get("patch", ""), encoding="utf-8")
    return root


def _parse_ruff_output(stdout: str) -> list[LintError]:
    errors: list[LintError] = []
    for line in stdout.strip().splitlines():
        # ruff format: path:line:col: CODE message
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        path, line_no, col, rest = parts
        code, _, message = rest.strip().partition(" ")
        errors.append(
            LintError(
                file=path,
                line=int(line_no),
                column=int(col),
                code=code,
                message=message.strip(),
                severity="error",
            )
        )
    return errors


def run_linter(state: AgentState) -> AgentState:
    """Lint changed files and route to patch generation or retry."""
    file_changes = state.get("file_changes", [])
    if not file_changes:
        return {"lint_errors": [], "status": "generating_patch"}

    root = _write_temp_files(file_changes)
    logger.info("Running ruff in %s", root)

    result = subprocess.run(
        ["ruff", "check", str(root)],
        capture_output=True,
        text=True,
    )

    lint_errors = _parse_ruff_output(result.stdout) if result.returncode != 0 else []

    next_status = "generating_patch" if lint_errors else "sandbox_running"
    return {
        "lint_errors": lint_errors,
        "status": next_status,
    }
