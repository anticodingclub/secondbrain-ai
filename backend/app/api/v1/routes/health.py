"""Liveness and readiness endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Response, status
from pydantic import BaseModel, Field

from app import __version__
from app.api.dependencies import ContainerDep
from app.db.session import check_database

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str
    environment: str


class DependencyStatus(BaseModel):
    healthy: bool
    detail: str | None = None


class ReadinessResponse(BaseModel):
    status: Literal["ready", "degraded"]
    version: str
    dependencies: dict[str, DependencyStatus] = Field(default_factory=dict)


@router.get("/health", response_model=HealthResponse, summary="Liveness probe")
async def health(container: ContainerDep) -> HealthResponse:
    """Answers 'is the process up'. Deliberately touches no dependency, so a
    slow database cannot cause an orchestrator to restart a healthy process."""
    return HealthResponse(version=__version__, environment=container.settings.environment)


@router.get("/health/ready", response_model=ReadinessResponse, summary="Readiness probe")
async def readiness(container: ContainerDep, response: Response) -> ReadinessResponse:
    """Answers 'can this instance serve traffic'. Returns 503 when it cannot, so
    a load balancer drains it instead of sending requests that will fail."""
    checks = {
        "database": await check_database(container.engine),
        "vector_store": await container.vector_store.health(),
    }
    dependencies = {
        name: DependencyStatus(healthy=ok, detail=None if ok else "unreachable")
        for name, ok in checks.items()
    }
    ready = all(checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(
        status="ready" if ready else "degraded",
        version=__version__,
        dependencies=dependencies,
    )
