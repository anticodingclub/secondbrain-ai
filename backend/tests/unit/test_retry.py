from __future__ import annotations

import pytest

from app.core.retry import with_retry


async def test_returns_immediately_when_the_call_succeeds() -> None:
    calls = 0

    async def succeed() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    assert await with_retry(succeed) == "ok"
    assert calls == 1


async def test_retries_transient_failures_then_succeeds() -> None:
    calls = 0

    async def flaky() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ConnectionError("upstream blip")
        return "recovered"

    result = await with_retry(flaky, initial_wait=0.01, max_wait=0.02)
    assert result == "recovered"
    assert calls == 3


async def test_reraises_after_exhausting_attempts() -> None:
    calls = 0

    async def always_fails() -> None:
        nonlocal calls
        calls += 1
        raise TimeoutError("gone")

    with pytest.raises(TimeoutError):
        await with_retry(always_fails, attempts=3, initial_wait=0.01, max_wait=0.02)
    assert calls == 3


async def test_does_not_retry_non_transient_failures() -> None:
    calls = 0

    async def bad_request() -> None:
        nonlocal calls
        calls += 1
        raise ValueError("this is our bug, not theirs")

    with pytest.raises(ValueError):
        await with_retry(bad_request, initial_wait=0.01)
    assert calls == 1
