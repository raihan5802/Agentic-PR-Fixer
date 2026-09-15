"""Tests for FastAPI webhook and review endpoints."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import MagicMock, patch

import pytest

from autopatch_agent.api.routes import parse_pull_request_webhook
from autopatch_agent.state import AgentState


WEBHOOK_SECRET = "test-webhook-secret"


def _sign_payload(payload: dict, secret: str = WEBHOOK_SECRET) -> str:
    body = json.dumps(payload).encode()
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _github_pr_payload(*, action: str = "opened") -> dict:
    return {
        "action": action,
        "repository": {"full_name": "acme/widget"},
        "pull_request": {
            "number": 17,
            "head": {
                "sha": "abc123deadbeef",
                "repo": {"clone_url": "https://github.com/acme/widget.git"},
            },
        },
    }


def test_parse_pull_request_webhook_extracts_fields():
    payload = _github_pr_payload(action="synchronize")
    fields = parse_pull_request_webhook(payload)

    assert fields == {
        "repo_name": "acme/widget",
        "pr_id": 17,
        "clone_url": "https://github.com/acme/widget.git",
        "head_sha": "abc123deadbeef",
    }


def test_github_webhook_rejects_invalid_signature(client):
    payload = _github_pr_payload()
    body = json.dumps(payload)

    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": "sha256=invalid",
        },
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid webhook signature"


def test_github_webhook_rejects_missing_signature(client):
    payload = _github_pr_payload()
    response = client.post(
        "/api/v1/webhooks/github",
        json=payload,
        headers={"X-GitHub-Event": "pull_request"},
    )

    assert response.status_code == 401


def test_github_webhook_accepts_valid_payload(client):
    payload = _github_pr_payload(action="opened")
    body = json.dumps(payload)
    signature = _sign_payload(payload)
    captured: dict = {}

    def _capture_run(initial_state: AgentState, thread_id: str) -> None:
        captured["initial_state"] = initial_state
        captured["thread_id"] = thread_id

    with patch("autopatch_agent.api.routes._run_workflow", side_effect=_capture_run):
        response = client.post(
            "/api/v1/webhooks/github",
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-GitHub-Event": "pull_request",
                "X-Hub-Signature-256": signature,
            },
        )

    assert response.status_code == 202
    assert response.json() == {
        "status": "processing",
        "thread_id": "acme/widget#17",
    }
    assert captured["thread_id"] == "acme/widget#17"
    assert captured["initial_state"]["repo_name"] == "acme/widget"
    assert captured["initial_state"]["pr_id"] == 17
    assert captured["initial_state"]["clone_url"] == "https://github.com/acme/widget.git"
    assert captured["initial_state"]["head_sha"] == "abc123deadbeef"


def test_github_webhook_ignores_non_pull_request_event(client):
    payload = {"action": "created"}
    body = json.dumps(payload)
    signature = _sign_payload(payload)

    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "issue_comment",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "ignored"


def test_github_webhook_ignores_unsupported_action(client):
    payload = _github_pr_payload(action="closed")
    body = json.dumps(payload)
    signature = _sign_payload(payload)

    response = client.post(
        "/api/v1/webhooks/github",
        content=body,
        headers={
            "Content-Type": "application/json",
            "X-GitHub-Event": "pull_request",
            "X-Hub-Signature-256": signature,
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "ignored"


def test_workflows_review_not_found(client):
    response = client.post(
        "/api/v1/workflows/review",
        json={"thread_id": "missing/repo#99", "approved": True},
    )
    assert response.status_code == 404


def _seed_review_state(graph, thread_id: str, **extra) -> dict:
    """
    Seed a workflow paused before ``human_review``.

    State is written as if ``execute_sandbox`` just routed to human review.
    """
    config = {"configurable": {"thread_id": thread_id}}
    state: AgentState = {
        "pr_id": extra.get("pr_id", 9),
        "repo_name": extra.get("repo_name", "acme/widget"),
        "status": "awaiting_human_review",
        "generated_patch": extra.get("generated_patch", "diff --git a/a.py b/a.py\n"),
        "patch_explanation": extra.get("patch_explanation", "fix lint"),
        "test_results": {"passed": True, "stdout": "ok", "stderr": "", "exit_code": 0},
        "human_approved": None,
        "retry_count": 0,
        "review_feedback": None,
    }
    graph.update_state(config, state, as_node="execute_sandbox")
    snapshot = graph.get_state(config)
    assert snapshot.next == ("human_review",), snapshot.next
    return config


def test_workflows_review_rejects_non_reviewable_state(client, workflow_graph):
    graph = workflow_graph
    thread_id = "acme/widget#5"
    config = {"configurable": {"thread_id": thread_id}}
    graph.update_state(
        config,
        {
            "pr_id": 5,
            "repo_name": "acme/widget",
            "status": "generating_patch",
            "retry_count": 0,
        },
        as_node="generate_patch",
    )

    response = client.post(
        "/api/v1/workflows/review",
        json={"thread_id": thread_id, "approved": True, "feedback": "n/a"},
    )

    assert response.status_code == 409


def test_workflows_review_rejection_terminates_thread(client, workflow_graph):
    graph = workflow_graph
    thread_id = "acme/widget#9"
    _seed_review_state(graph, thread_id)
    config = {"configurable": {"thread_id": thread_id}}

    response = client.post(
        "/api/v1/workflows/review",
        json={
            "thread_id": thread_id,
            "approved": False,
            "feedback": "Needs more test coverage",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "rejected"
    assert body["state"]["review_feedback"] == "Needs more test coverage"
    assert body["state"]["human_approved"] is False

    final = graph.get_state(config).values
    assert final["status"] == "rejected"


def test_workflows_review_approval_resumes_and_posts_comment(client, workflow_graph):
    graph = workflow_graph
    thread_id = "acme/widget#3"
    _seed_review_state(
        graph,
        thread_id,
        pr_id=3,
        generated_patch="diff --git a/a.py b/a.py\n+fix\n",
        patch_explanation="Resolved lint error",
    )
    config = {"configurable": {"thread_id": thread_id}}

    with patch(
        "autopatch_agent.api.routes.post_approved_patch_comment",
        return_value=999,
    ) as mock_post:
        response = client.post(
            "/api/v1/workflows/review",
            json={
                "thread_id": thread_id,
                "approved": True,
                "feedback": "LGTM",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["state"]["human_approved"] is True
    assert body["state"]["review_feedback"] == "LGTM"

    mock_post.assert_called_once_with(
        repo_name="acme/widget",
        pr_id=3,
        patch_diff="diff --git a/a.py b/a.py\n+fix\n",
        explanation="Resolved lint error",
        feedback="LGTM",
    )


def test_workflows_review_approval_resumes_graph_stream(client, workflow_graph):
    """Ensure graph.stream resumes through the human_review node to completion."""
    graph = workflow_graph
    thread_id = "acme/widget#11"
    config = _seed_review_state(graph, thread_id, pr_id=11)

    with patch("autopatch_agent.api.routes.post_approved_patch_comment", return_value=1):
        response = client.post(
            "/api/v1/workflows/review",
            json={"thread_id": thread_id, "approved": True},
        )

    assert response.status_code == 200
    assert graph.get_state(config).values["status"] == "completed"
