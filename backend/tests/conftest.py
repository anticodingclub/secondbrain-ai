"""Shared fixtures.

By default every test gets its own SQLite file and embedded Qdrant directory,
so the suite runs anywhere with no services and tests stay order-independent.

Setting ``SECONDBRAIN_DATABASE_URL`` and ``SECONDBRAIN_QDRANT_URL`` runs the
*same* suite against real Postgres and a real Qdrant server, which is what CI
does. Without that, "the dual-dialect models also work on Postgres" would be a
claim rather than a fact — the UTCDateTime decorator, the JSONB variants and
the native UUID type are only exercised on whichever backend actually runs.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Environment, Settings
from app.db.base import Base
from app.db.session import create_engine, create_session_factory
from app.main import create_app

#: Set by CI to point the suite at the production stack.
EXTERNAL_DATABASE_URL = os.environ.get("SECONDBRAIN_DATABASE_URL")
EXTERNAL_QDRANT_URL = os.environ.get("SECONDBRAIN_QDRANT_URL")

RUNNING_AGAINST_POSTGRES = bool(
    EXTERNAL_DATABASE_URL and EXTERNAL_DATABASE_URL.startswith("postgresql")
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.TEST,
        debug=True,
        log_level="WARNING",
        # One SQLite file per test via tmp_path; against Postgres every test
        # shares one database and is isolated by dropping the schema instead.
        database_url=EXTERNAL_DATABASE_URL or f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        qdrant_url=EXTERNAL_QDRANT_URL,
        qdrant_path=None if EXTERNAL_QDRANT_URL else tmp_path / "qdrant",
        # Unique per test either way, so vectors never leak between tests even
        # on a shared Qdrant server.
        qdrant_collection=f"test_{uuid.uuid4().hex[:8]}",
        storage_path=tmp_path / "storage",
        secret_key="test-secret-key-not-used-in-production",
    )


@pytest.fixture
async def engine(settings: Settings) -> AsyncIterator[AsyncEngine]:
    engine = create_engine(settings)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return create_session_factory(engine)


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as session:
        yield session
        await session.rollback()


@pytest.fixture
def app(settings: Settings) -> Iterator[FastAPI]:
    application = create_app(settings)
    yield application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Exercises the real app through its ASGI interface, including middleware
    and exception handlers — a TestClient that bypassed those would not catch
    the bugs those layers introduce."""
    container = app.state.container

    async with container.engine.begin() as conn:
        # On a shared Postgres the previous test's rows are still there, so
        # the schema is rebuilt rather than merely ensured. On SQLite the
        # database is a fresh file and the drop is a no-op.
        if RUNNING_AGAINST_POSTGRES:
            await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac

    # Qdrant collections are per-test but a shared server would otherwise
    # accumulate one per test for the life of the process.
    if EXTERNAL_QDRANT_URL:
        # Cleanup must never turn a passing test red.
        with contextlib.suppress(Exception):  # pragma: no cover
            await container.vector_store.drop_collection()
