"""Tenacity-based exponential backoff for rate limits and server errors."""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

RETRYABLE_HTTP_STATUS = frozenset({429, 500, 502, 503, 504})
DEFAULT_RETRY_ATTEMPTS = 5

F = TypeVar("F", bound=Callable[..., Any])


def is_retryable_api_error(exc: BaseException) -> bool:
    """Return True for GitHub/LLM rate limits and transient 5xx failures."""
    try:
        from github import GithubException, RateLimitExceededException
    except ImportError:  # pragma: no cover
        GithubException = ()  # type: ignore[misc, assignment]
        RateLimitExceededException = ()  # type: ignore[misc, assignment]

    if isinstance(exc, RateLimitExceededException):
        return True

    if isinstance(exc, GithubException):
        return exc.status in RETRYABLE_HTTP_STATUS

    status_code = getattr(exc, "status_code", None)
    if status_code in RETRYABLE_HTTP_STATUS:
        return True

    response = getattr(exc, "response", None)
    if response is not None:
        response_status = getattr(response, "status_code", None)
        if response_status in RETRYABLE_HTTP_STATUS:
            return True

    exc_name = type(exc).__name__
    if "RateLimit" in exc_name or "InternalServerError" in exc_name:
        return True

    return False


def api_retry(*, attempts: int = DEFAULT_RETRY_ATTEMPTS) -> Callable[[F], F]:
    """Decorator applying exponential backoff on retryable API failures."""
    return retry(
        retry=retry_if_exception(is_retryable_api_error),
        wait=wait_exponential(multiplier=1, min=1, max=60),
        stop=stop_after_attempt(attempts),
        reraise=True,
        before_sleep=before_sleep_log(logger, logging.WARNING),
    )
