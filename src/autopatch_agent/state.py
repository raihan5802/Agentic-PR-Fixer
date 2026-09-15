"""LangGraph state definitions for the AutoPatch workflow."""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages


WorkflowStatus = Literal[
    "pending",
    "fetching_pr",
    "linting",
    "generating_patch",
    "sandbox_running",
    "awaiting_human_review",
    "approved",
    "rejected",
    "failed",
    "completed",
]


class FileChange(TypedDict, total=False):
    """A single file modification extracted from a pull request."""

    path: str
    patch: str
    status: Literal["added", "modified", "removed", "renamed"]
    additions: int
    deletions: int


class LintError(TypedDict, total=False):
    """Structured linter diagnostic."""

    file: str
    line: int
    column: int
    code: str
    message: str
    severity: Literal["error", "warning", "info"]


class TestResult(TypedDict, total=False):
    """Outcome of sandbox test execution."""

    passed: bool
    stdout: str
    stderr: str
    exit_code: int
    duration_seconds: float


def merge_file_changes(
    existing: list[FileChange] | None,
    incoming: list[FileChange] | None,
) -> list[FileChange]:
    """Reducer: replace file changes when new data arrives."""
    if incoming is not None:
        return incoming
    return existing or []


def merge_lint_errors(
    existing: list[LintError] | None,
    incoming: list[LintError] | None,
) -> list[LintError]:
    """Reducer: accumulate lint errors across retries."""
    return (existing or []) + (incoming or [])


def increment_retry(existing: int | None, incoming: int | None) -> int:
    """Reducer: increment retry counter when a node signals a retry."""
    base = existing or 0
    if incoming is None:
        return base
    return base + incoming


class AgentState(TypedDict, total=False):
    """
    Shared LangGraph state for the AutoPatch agent workflow.

    Fields marked with reducers are merged across node transitions;
    scalar fields are last-write-wins unless otherwise noted.
    """

    # Identity
    pr_id: int
    repo_name: str
    clone_url: str | None
    head_sha: str | None

    # PR content
    file_changes: Annotated[list[FileChange], merge_file_changes]
    lint_errors: Annotated[list[LintError], merge_lint_errors]

    # Agent outputs
    generated_patch: str | None
    patch_explanation: str | None
    test_results: TestResult | None

    # Control flow
    retry_count: Annotated[int, increment_retry]
    human_approved: bool | None
    review_feedback: str | None
    status: WorkflowStatus

    # Optional audit trail for LLM/tool messages
    messages: Annotated[list[Any], add_messages]

    # Error context propagated to downstream nodes
    error: str | None
