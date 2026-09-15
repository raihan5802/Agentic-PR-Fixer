"""Fetch pull request metadata and file diffs from GitHub."""

from __future__ import annotations

import logging

from autopatch_agent.services.github import fetch_pull_request_files
from autopatch_agent.state import AgentState

logger = logging.getLogger(__name__)


def fetch_pr(state: AgentState) -> AgentState:
    """Retrieve PR file changes and transition to linting."""
    repo_name = state["repo_name"]
    pr_id = state["pr_id"]

    logger.info("Fetching PR #%s from %s", pr_id, repo_name)
    file_changes = fetch_pull_request_files(repo_name, pr_id)

    return {
        "file_changes": file_changes,
        "status": "linting",
        "error": None,
    }
