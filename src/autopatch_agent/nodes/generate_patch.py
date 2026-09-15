"""Generate a unified diff patch using an LLM to fix lint errors."""

from __future__ import annotations

import logging

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from autopatch_agent.config import LLMProvider, get_settings
from autopatch_agent.resilience.retry import api_retry
from autopatch_agent.state import AgentState

logger = logging.getLogger(__name__)

PATCH_PROMPT = """\
You are a senior software engineer. Fix the lint errors in the following pull request changes.

Repository: {repo_name}
PR ID: {pr_id}

Lint errors:
{lint_errors}

File changes:
{file_changes}
{self_correction}
Produce a valid unified diff patch that resolves the lint errors and passes tests.
"""

SELF_CORRECTION_PROMPT = """
SELF-CORRECTION (attempt #{retry_count}):
Your previous patch failed validation. Learn from the failure output below and
produce a corrected patch.

Previous test results:
  stdout: {test_stdout}
  stderr: {test_stderr}
  exit_code: {exit_code}

Remaining lint errors:
{lint_errors}
"""


class PatchOutput(BaseModel):
    """Structured LLM output for patch generation."""

    patch_diff: str = Field(description="Unified diff patch applying the fix")
    explanation: str = Field(description="Brief rationale for the proposed changes")


def _build_llm():
    settings = get_settings()
    api_key = settings.resolve_llm_api_key().get_secret_value()

    if settings.llm_provider == LLMProvider.ANTHROPIC:
        return ChatAnthropic(model=settings.llm_model, api_key=api_key)

    return ChatOpenAI(model=settings.llm_model, api_key=api_key)


def _build_self_correction_block(state: AgentState) -> str:
    retry_count = state.get("retry_count", 0)
    if retry_count <= 0:
        return ""

    test_results = state.get("test_results") or {}
    return SELF_CORRECTION_PROMPT.format(
        retry_count=retry_count,
        test_stdout=test_results.get("stdout", ""),
        test_stderr=test_results.get("stderr", ""),
        exit_code=test_results.get("exit_code", "unknown"),
        lint_errors=state.get("lint_errors", []),
    )


def build_patch_prompt(state: AgentState) -> str:
    """Build the LLM prompt, including self-correction context on retries."""
    return PATCH_PROMPT.format(
        repo_name=state["repo_name"],
        pr_id=state["pr_id"],
        lint_errors=state.get("lint_errors", []),
        file_changes=state.get("file_changes", []),
        self_correction=_build_self_correction_block(state),
    )


@api_retry()
def _invoke_patch_llm(llm, prompt: str) -> PatchOutput:
    """Invoke the structured-output LLM with retry on rate limits."""
    return llm.invoke(prompt)


def generate_patch(state: AgentState) -> AgentState:
    """Invoke LLM with structured output to produce a fix patch from diagnostics."""
    llm = _build_llm().with_structured_output(PatchOutput)
    prompt = build_patch_prompt(state)

    logger.info(
        "Generating patch for PR #%s (retry_count=%s)",
        state["pr_id"],
        state.get("retry_count", 0),
    )
    output: PatchOutput = _invoke_patch_llm(llm, prompt)

    return {
        "generated_patch": output.patch_diff,
        "patch_explanation": output.explanation,
        "status": "sandbox_running",
        "error": None,
    }
