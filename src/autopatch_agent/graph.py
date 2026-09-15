"""LangGraph StateGraph builder and checkpointer compilation."""

from __future__ import annotations

import logging
import sqlite3
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph

from autopatch_agent.config import CheckpointBackend, Settings, get_settings
from autopatch_agent.edges import (
    route_after_human_review,
    route_after_lint,
    should_retry_or_approve,
)
from autopatch_agent.nodes import (
    execute_sandbox,
    fetch_pr,
    generate_patch,
    human_review,
    run_linter,
)
from autopatch_agent.nodes.escalate_fallback import escalate_fallback
from autopatch_agent.state import AgentState

logger = logging.getLogger(__name__)

_CHECKPOINTER: Any | None = None
_CHECKPOINTER_CTX: AbstractContextManager[Any] | None = None
_COMPILED_GRAPH = None


def build_checkpointer(settings: Settings | None = None) -> Any:
    """Create a LangGraph checkpointer based on configured backend."""
    settings = settings or get_settings()

    if settings.checkpoint_backend == CheckpointBackend.REDIS:
        from langgraph.checkpoint.redis import RedisSaver

        logger.info("Using Redis checkpointer at %s", settings.redis_url)
        ctx = RedisSaver.from_conn_string(settings.redis_url)
        if hasattr(ctx, "__enter__"):
            global _CHECKPOINTER_CTX
            _CHECKPOINTER_CTX = ctx
            return ctx.__enter__()
        return ctx

    if settings.checkpoint_backend == CheckpointBackend.SQLITE:
        from langgraph.checkpoint.sqlite import SqliteSaver

        db_path = settings.checkpoint_db_url.removeprefix("sqlite:///")
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        logger.info("Using SQLite checkpointer at %s", db_path)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        return SqliteSaver(conn)

    logger.info("Using in-memory checkpointer")
    return MemorySaver()


def shutdown_checkpointer() -> None:
    """Release managed checkpointer resources (Redis context manager)."""
    global _CHECKPOINTER_CTX
    if _CHECKPOINTER_CTX is not None:
        _CHECKPOINTER_CTX.__exit__(None, None, None)
        _CHECKPOINTER_CTX = None


def build_graph(*, checkpointer=None):
    """Construct and compile the AutoPatch workflow graph."""
    graph = StateGraph(AgentState)

    graph.add_node("fetch_pr", fetch_pr)
    graph.add_node("run_linter", run_linter)
    graph.add_node("generate_patch", generate_patch)
    graph.add_node("execute_sandbox", execute_sandbox)
    graph.add_node("human_review", human_review)
    graph.add_node("escalate_fallback", escalate_fallback)

    graph.set_entry_point("fetch_pr")
    graph.add_edge("fetch_pr", "run_linter")
    graph.add_conditional_edges("run_linter", route_after_lint)
    graph.add_edge("generate_patch", "execute_sandbox")
    graph.add_conditional_edges("execute_sandbox", should_retry_or_approve)
    graph.add_conditional_edges("human_review", route_after_human_review)
    graph.add_edge("escalate_fallback", "__end__")

    compiled = graph.compile(
        checkpointer=checkpointer or build_checkpointer(),
        interrupt_before=["human_review"],
    )
    return compiled


def _get_checkpointer() -> Any:
    global _CHECKPOINTER
    if _CHECKPOINTER is None:
        _CHECKPOINTER = build_checkpointer()
    return _CHECKPOINTER


def get_compiled_graph():
    """Return a process-wide compiled graph backed by a shared checkpointer."""
    global _COMPILED_GRAPH
    if _COMPILED_GRAPH is None:
        _COMPILED_GRAPH = build_graph(checkpointer=_get_checkpointer())
    return _COMPILED_GRAPH


def reset_compiled_graph(*, checkpointer: Any | None = None) -> None:
    """Reset the graph singleton (used in tests)."""
    global _COMPILED_GRAPH, _CHECKPOINTER
    shutdown_checkpointer()
    _CHECKPOINTER = checkpointer or MemorySaver()
    _COMPILED_GRAPH = build_graph(checkpointer=_CHECKPOINTER)
