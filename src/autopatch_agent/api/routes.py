"""FastAPI webhook listener and workflow control routes."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from autopatch_agent.config import get_settings
from autopatch_agent.graph import get_compiled_graph
from autopatch_agent.services.github import post_approved_patch_comment
from autopatch_agent.state import AgentState

logger = logging.getLogger(__name__)
router = APIRouter()

SUPPORTED_PR_ACTIONS = frozenset({"opened", "synchronize"})


class WorkflowStartRequest(BaseModel):
    repo_name: str = Field(..., examples=["owner/repo"])
    pr_id: int = Field(..., ge=1)


class HumanReviewRequest(BaseModel):
    thread_id: str
    approved: bool
    feedback: str | None = None


class WorkflowResponse(BaseModel):
    thread_id: str
    status: str
    state: dict[str, Any]


class WebhookAcceptedResponse(BaseModel):
    status: str
    thread_id: str


def _verify_github_signature(payload: bytes, signature: str | None, secret: str) -> None:
    if not signature or not signature.startswith("sha256="):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or malformed X-Hub-Signature-256 header",
        )

    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(f"sha256={expected}", signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )


def parse_pull_request_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract workflow fields from a GitHub pull_request webhook payload."""
    pr = payload["pull_request"]
    return {
        "repo_name": payload["repository"]["full_name"],
        "pr_id": pr["number"],
        "clone_url": pr["head"]["repo"]["clone_url"],
        "head_sha": pr["head"]["sha"],
    }


def _build_thread_config(thread_id: str) -> dict[str, Any]:
    return {"configurable": {"thread_id": thread_id}}


def _run_workflow(initial_state: AgentState, thread_id: str) -> None:
    """Background task entrypoint for LangGraph execution."""
    graph = get_compiled_graph()
    config = _build_thread_config(thread_id)
    try:
        graph.invoke(initial_state, config=config)
        logger.info("Workflow finished for %s", thread_id)
    except Exception:
        logger.exception("Workflow failed for %s", thread_id)


def _extract_final_state(graph, config: dict[str, Any]) -> dict[str, Any]:
    snapshot = graph.get_state(config)
    if snapshot and snapshot.values:
        return dict(snapshot.values)
    return {}


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "autopatch-agent"}


@router.post(
    "/webhooks/github",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=WebhookAcceptedResponse,
)
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: str | None = Header(default=None, alias="X-Hub-Signature-256"),
    x_github_event: str | None = Header(default=None, alias="X-GitHub-Event"),
) -> WebhookAcceptedResponse:
    """Handle GitHub pull_request webhooks and enqueue workflow runs."""
    settings = get_settings()
    body = await request.body()

    if settings.github_webhook_secret is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GitHub webhook secret is not configured",
        )
    _verify_github_signature(
        body,
        x_hub_signature_256,
        settings.github_webhook_secret.get_secret_value(),
    )

    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        ) from exc

    if x_github_event != "pull_request":
        return WebhookAcceptedResponse(status="ignored", thread_id="")

    action = payload.get("action")
    if action not in SUPPORTED_PR_ACTIONS:
        return WebhookAcceptedResponse(status="ignored", thread_id="")

    fields = parse_pull_request_webhook(payload)
    thread_id = f"{fields['repo_name']}#{fields['pr_id']}"

    initial_state: AgentState = {
        "pr_id": fields["pr_id"],
        "repo_name": fields["repo_name"],
        "clone_url": fields["clone_url"],
        "head_sha": fields["head_sha"],
        "status": "pending",
        "retry_count": 0,
        "human_approved": None,
        "review_feedback": None,
    }

    background_tasks.add_task(_run_workflow, initial_state, thread_id)
    logger.info("Queued workflow for %s (head=%s)", thread_id, fields["head_sha"])

    return WebhookAcceptedResponse(status="processing", thread_id=thread_id)


@router.post("/workflows/start", response_model=WorkflowResponse)
async def start_workflow(body: WorkflowStartRequest) -> WorkflowResponse:
    """Manually trigger a workflow run."""
    thread_id = f"{body.repo_name}#{body.pr_id}"
    graph = get_compiled_graph()

    initial_state: AgentState = {
        "pr_id": body.pr_id,
        "repo_name": body.repo_name,
        "status": "pending",
        "retry_count": 0,
        "human_approved": None,
        "review_feedback": None,
    }
    result = graph.invoke(initial_state, config=_build_thread_config(thread_id))

    return WorkflowResponse(
        thread_id=thread_id,
        status=result.get("status", "unknown"),
        state=dict(result),
    )


@router.post("/workflows/review", response_model=WorkflowResponse)
async def submit_human_review(body: HumanReviewRequest) -> WorkflowResponse:
    """Resume or terminate an interrupted workflow after human review."""
    graph = get_compiled_graph()
    config = _build_thread_config(body.thread_id)

    snapshot = graph.get_state(config)
    if snapshot is None or not snapshot.values:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No workflow found for thread_id={body.thread_id}",
        )

    current_status = snapshot.values.get("status")
    if current_status != "awaiting_human_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Workflow is not awaiting review (status={current_status!r}) "
                f"for thread_id={body.thread_id}"
            ),
        )

    if body.approved:
        graph.update_state(
            config,
            {
                "human_approved": True,
                "review_feedback": body.feedback,
            },
            as_node="execute_sandbox",
        )

        for _event in graph.stream(None, config=config):
            pass

        final_state = _extract_final_state(graph, config)
        patch = final_state.get("generated_patch")
        if not patch:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Approved workflow is missing generated_patch",
            )

        post_approved_patch_comment(
            repo_name=final_state["repo_name"],
            pr_id=final_state["pr_id"],
            patch_diff=patch,
            explanation=final_state.get("patch_explanation"),
            feedback=body.feedback,
        )

        return WorkflowResponse(
            thread_id=body.thread_id,
            status=final_state.get("status", "completed"),
            state=final_state,
        )

    graph.update_state(
        config,
        {
            "human_approved": False,
            "review_feedback": body.feedback,
            "status": "rejected",
        },
        as_node="execute_sandbox",
    )

    for _event in graph.stream(None, config=config):
        pass

    final_state = _extract_final_state(graph, config)
    return WorkflowResponse(
        thread_id=body.thread_id,
        status=final_state.get("status", "rejected"),
        state=final_state,
    )
