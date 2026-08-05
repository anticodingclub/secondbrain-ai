"""Framework behaviour the application depends on.

Deliberately no ``from __future__ import annotations`` here: FastAPI resolves
parameter types at runtime, and stringised annotations on locally-defined
routes cannot be resolved from a function scope.

These tests assert nothing about our own code. They exist because an upgrade
that quietly changes one of these behaviours would break the application in a
way that is very hard to trace back to its cause.
"""

from collections.abc import AsyncIterator
from typing import Annotated

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI
from httpx import ASGITransport, AsyncClient

pytestmark = pytest.mark.integration

_order: list[str] = []


async def _dependency() -> AsyncIterator[str]:
    yield "resource"
    _order.append("dependency_exit")


async def _task() -> None:
    _order.append("background_task")


probe = FastAPI()


@probe.get("/")
async def _endpoint(
    background: BackgroundTasks,
    resource: Annotated[str, Depends(_dependency)],
) -> dict[str, str]:
    background.add_task(_task)
    return {"resource": resource}


async def test_background_tasks_run_before_dependency_teardown() -> None:
    """Locks in the ordering the upload route works around.

    Background tasks run *before* `yield` dependencies exit, so a task
    scheduled from a handler cannot see anything the request session has not
    already committed. That is why `POST /documents/upload` commits explicitly
    before scheduling the parse — without it, every upload sat at `pending`
    while the log filled with `parse_target_missing`.

    If a future FastAPI reverses this, that explicit commit becomes
    unnecessary, and this test failing is the signal to revisit it.
    """
    _order.clear()

    async with AsyncClient(transport=ASGITransport(app=probe), base_url="http://t") as client:
        response = await client.get("/")

    assert response.status_code == 200, response.text
    assert _order == ["background_task", "dependency_exit"]
