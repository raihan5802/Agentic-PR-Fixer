"""Human-in-the-loop approval gate."""

from __future__ import annotations

import logging

from autopatch_agent.state import AgentState

logger = logging.getLogger(__name__)


def human_review(state: AgentState) -> AgentState:
    """
    Pause for human approval.

    In production this node is typically interrupted by LangGraph;
    resume updates `human_approved` via the API.
    """
    approved = state.get("human_approved")

    if approved is None:
        logger.info("Awaiting human review for PR #%s", state["pr_id"])
        return {"status": "awaiting_human_review"}

    if approved:
        return {"status": "completed"}

    return {"status": "rejected"}
