"""Conditional routing logic for the AutoPatch LangGraph."""

from __future__ import annotations

from autopatch_agent.config import get_settings
from autopatch_agent.state import AgentState, WorkflowStatus


def route_after_lint(state: AgentState) -> str:
    """Route to patch generation when lint errors exist, else skip to sandbox."""
    if state.get("lint_errors"):
        return "generate_patch"
    return "execute_sandbox"


def should_retry_or_approve(state: AgentState) -> str:
    """
    Route after sandbox execution.

    - Tests passed -> human review
    - Tests failed with retries remaining -> regenerate patch
    - Retry budget exhausted -> escalate to manual fallback
    """
    test_results = state.get("test_results") or {}
    if test_results.get("passed") is True:
        return "human_review"

    settings = get_settings()
    retry_count = state.get("retry_count", 0)
    if retry_count < settings.max_retry_count:
        return "generate_patch"

    return "escalate_fallback"


def route_after_human_review(state: AgentState) -> str:
    """Terminate when approved/rejected; otherwise stay interrupted."""
    approved = state.get("human_approved")
    if approved is True:
        return "__end__"
    if approved is False:
        return "__end__"
    return "human_review"


def route_on_status(state: AgentState) -> WorkflowStatus:
    """Map terminal statuses for observability hooks."""
    return state.get("status", "pending")
