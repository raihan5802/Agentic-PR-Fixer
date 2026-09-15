"""GitHub API helpers for PR interactions."""

from __future__ import annotations

import logging

from github import Auth, Github

from autopatch_agent.config import get_settings
from autopatch_agent.resilience.retry import api_retry
from autopatch_agent.state import FileChange

logger = logging.getLogger(__name__)


def _github_client() -> Github:
    settings = get_settings()
    return Github(auth=Auth.Token(settings.github_token.get_secret_value()))


@api_retry()
def fetch_pull_request_files(repo_name: str, pr_id: int) -> list[FileChange]:
    """Fetch PR file diffs with exponential backoff on rate limits."""
    client = _github_client()
    pull = client.get_repo(repo_name).get_pull(pr_id)
    return [
        FileChange(
            path=file.filename or "",
            patch=file.patch or "",
            status=file.status,  # type: ignore[typeddict-item]
            additions=file.additions,
            deletions=file.deletions,
        )
        for file in pull.get_files()
    ]


@api_retry()
def post_approved_patch_comment(
    *,
    repo_name: str,
    pr_id: int,
    patch_diff: str,
    explanation: str | None = None,
    feedback: str | None = None,
) -> int:
    """
    Post an approved AutoPatch as a pull request comment.

    Returns the created comment ID.
    """
    client = _github_client()
    pull = client.get_repo(repo_name).get_pull(pr_id)

    body_parts = [
        "## AutoPatch Approved :white_check_mark:",
        "",
        "An automated patch was reviewed and approved.",
    ]
    if explanation:
        body_parts.extend(["", f"**Explanation:** {explanation}"])
    if feedback:
        body_parts.extend(["", f"**Reviewer feedback:** {feedback}"])
    body_parts.extend(["", "### Patch", "", "```diff", patch_diff, "```"])

    comment = pull.create_issue_comment("\n".join(body_parts))
    logger.info("Posted approved patch comment on %s#%s (comment_id=%s)", repo_name, pr_id, comment.id)
    return comment.id
