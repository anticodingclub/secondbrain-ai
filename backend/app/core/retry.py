"""Retry policy for calls to dependencies we do not control.

Embedding APIs, LLM providers and Qdrant all fail transiently under load. A
single shared policy means retry behaviour is consistent and observable rather
than reinvented (and mistuned) at each call site.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from tenacity import (
    AsyncRetrying,
    RetryCallState,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from app.core.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")

#: Failures worth retrying. Anything else (a 400, a validation error) is a bug
#: in our request and retrying only multiplies the damage.
TRANSIENT_EXCEPTIONS: tuple[type[BaseException], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


def _log_attempt(state: RetryCallState) -> None:
    exc = state.outcome.exception() if state.outcome else None
    logger.warning(
        "retrying_after_transient_failure",
        attempt=state.attempt_number,
        sleep_seconds=round(state.next_action.sleep, 3) if state.next_action else None,
        error=repr(exc),
    )


def retry_policy(
    *,
    attempts: int = 3,
    initial_wait: float = 0.5,
    max_wait: float = 8.0,
    exceptions: tuple[type[BaseException], ...] = TRANSIENT_EXCEPTIONS,
) -> AsyncRetrying:
    """Build an ``AsyncRetrying`` with exponential backoff and full jitter.

    Jitter matters: without it, every worker that failed on the same upstream
    blip retries in lockstep and re-creates the thundering herd that caused it.
    """
    return AsyncRetrying(
        stop=stop_after_attempt(attempts),
        wait=wait_exponential_jitter(initial=initial_wait, max=max_wait),
        retry=retry_if_exception_type(exceptions),
        before_sleep=_log_attempt,
        reraise=True,
    )


async def with_retry(
    fn: Callable[[], Any],
    *,
    attempts: int = 3,
    initial_wait: float = 0.5,
    max_wait: float = 8.0,
    exceptions: tuple[type[BaseException], ...] = TRANSIENT_EXCEPTIONS,
) -> Any:
    """Await ``fn()`` under the shared retry policy."""
    async for attempt in retry_policy(
        attempts=attempts,
        initial_wait=initial_wait,
        max_wait=max_wait,
        exceptions=exceptions,
    ):
        with attempt:
            return await fn()
    raise AssertionError("unreachable: retry_policy always reraises or returns")
