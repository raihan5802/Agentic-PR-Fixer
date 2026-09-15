"""Tests for LangGraph workflow assembly."""

from __future__ import annotations

from langgraph.checkpoint.memory import MemorySaver

from autopatch_agent.graph import build_graph


def test_build_graph_contains_required_nodes():
    graph = build_graph(checkpointer=MemorySaver())
    node_names = set(graph.get_graph().nodes.keys())

    expected = {
        "fetch_pr",
        "run_linter",
        "generate_patch",
        "execute_sandbox",
        "human_review",
        "escalate_fallback",
        "__start__",
        "__end__",
    }
    assert expected.issubset(node_names)


def test_build_graph_uses_memory_checkpointer_by_default():
    graph = build_graph(checkpointer=MemorySaver())
    assert graph.checkpointer is not None
