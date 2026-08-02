"""Shared fixtures.

Each test gets its own in-memory database and a throwaway embedded Qdrant
directory, so tests are order-independent and safe to run in parallel.
"""

from __future__ import annotations

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


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        environment=Environment.TEST,
        debug=True,
        log_level="WARNING",
        # StaticPool-free shared in-memory DB: one URI per test via tmp_path.
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'test.db'}",
        qdrant_url=None,
        qdrant_path=tmp_path / "qdrant",
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
    from app.db.base import Base as MetadataBase

    container = app.state.container
    async with container.engine.begin() as conn:
        await conn.run_sync(MetadataBase.metadata.create_all)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac
