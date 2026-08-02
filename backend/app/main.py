"""Application factory.

There is deliberately no module-level ``app`` instance: importing this module
must not build a database engine or touch the filesystem. Serve it with

    uvicorn app.main:create_app --factory
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import __version__
from app.api.errors import register_exception_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.v1.router import api_router
from app.core.config import Environment, Settings, get_settings
from app.core.container import Container
from app.core.logging import configure_logging, get_logger

logger = get_logger(__name__)

DESCRIPTION = """
**SecondBrain AI** — a local-first personal search engine.

Index documents, code and media you own, then query them in natural language
with retrieval-augmented answers and page-level citations.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    container: Container = app.state.container
    await container.startup()
    logger.info(
        "application_started",
        version=__version__,
        environment=container.settings.environment,
    )
    try:
        yield
    finally:
        await container.shutdown()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the ASGI application.

    Taking ``settings`` as an argument (rather than reading globals) is what
    makes the test suite able to spin up an isolated app per test module.
    """
    settings = settings or get_settings()
    configure_logging(settings)

    is_production = settings.environment is Environment.PRODUCTION

    app = FastAPI(
        title=settings.app_name,
        description=DESCRIPTION,
        version=__version__,
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )
    app.state.container = Container.build(settings)

    # Middleware runs bottom-up, so RequestContextMiddleware is added last and
    # executes first — every later layer then logs with a correlation id.
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,  # required for the httpOnly refresh cookie in Phase 2
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    return app
