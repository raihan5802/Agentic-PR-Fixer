"""Terminal fallback when automated patch retries are exhausted."""

from __future__ import annotations

import logging

from autopatch_agent.config import get_settings
from autopatch_agent.state import AgentState

logger = logging.getLogger(__name__)


def escalate_fallback(state: AgentState) -> AgentState:
    """Escalate to manual handling after exceeding the retry budget."""
    settings = get_settings()
    retry_count = state.get("retry_count", 0)

    logger.warning(
        "Escalating PR #%s after %s retries (max=%s)",
        state.get("pr_id"),
        retry_count,
        settings.max_retry_count,
    )

    test_results = state.get("test_results") or {}
    return {
        "status": "failed",
        "error": (
            f"Automated patch retries exhausted ({retry_count}/{settings.max_retry_count}). "
            f"Last stderr: {test_results.get('stderr', 'n/a')}"
        ),
    }
