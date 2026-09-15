"""Tests for LangGraph state definitions."""

from __future__ import annotations

from autopatch_agent.state import (
    increment_retry,
    merge_file_changes,
    merge_lint_errors,
)


def test_merge_file_changes_replaces_on_incoming():
    existing = [{"path": "a.py", "patch": "old"}]
    incoming = [{"path": "b.py", "patch": "new"}]
    assert merge_file_changes(existing, incoming) == incoming


def test_merge_file_changes_keeps_existing_when_incoming_none():
    existing = [{"path": "a.py", "patch": "old"}]
    assert merge_file_changes(existing, None) == existing


def test_merge_lint_errors_accumulates():
    existing = [{"file": "a.py", "line": 1, "message": "err1"}]
    incoming = [{"file": "b.py", "line": 2, "message": "err2"}]
    result = merge_lint_errors(existing, incoming)
    assert len(result) == 2


def test_increment_retry_adds_incoming():
    assert increment_retry(1, 1) == 2


def test_increment_retry_returns_base_when_incoming_none():
    assert increment_retry(2, None) == 2
