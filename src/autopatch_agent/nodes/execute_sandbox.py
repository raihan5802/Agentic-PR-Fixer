"""Execute tests inside an isolated Docker sandbox."""

from __future__ import annotations

import logging

from autopatch_agent.sandbox import SandboxRunner
from autopatch_agent.state import AgentState

logger = logging.getLogger(__name__)


def execute_sandbox(state: AgentState) -> AgentState:
    """Run pytest/ruff validation in a container with the generated patch."""
    patch = state.get("generated_patch")
    if not patch:
        return {
            "status": "failed",
            "error": "No generated patch available for sandbox execution",
        }

    logger.info("Executing sandbox for PR #%s", state["pr_id"])
    runner = SandboxRunner()
    test_results = runner.run(patch=patch, repo_name=state["repo_name"])

    update: AgentState = {
        "test_results": test_results,
        "status": "sandbox_running",
    }

    if test_results.get("passed"):
        update["status"] = "awaiting_human_review"
        return update

    update["status"] = "generating_patch"
    update["retry_count"] = 1
    update["error"] = test_results.get("stderr") or test_results.get("error")
    return update
