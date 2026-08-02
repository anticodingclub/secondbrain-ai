"""Async engine and session lifecycle.

The engine is created once per process and owned by the application lifespan.
Sessions are per-request and never shared across tasks — an ``AsyncSession`` is
not concurrency-safe.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _sqlite_pragmas(dbapi_connection: Any, _record: Any) -> None:
    """Make SQLite behave enough like Postgres for development to be meaningful.

    WAL allows concurrent readers alongside the indexing writer, and foreign
    keys are OFF by default in SQLite, which would silently hide referential
    bugs that Postgres would reject in production.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def ensure_sqlite_directory(settings: Settings) -> None:
    """Create the parent directory of a file-backed SQLite database."""
    if not settings.is_sqlite:
        return
    _, _, location = settings.database_url.partition(":///")
    if not location or location == ":memory:":
        return
    Path(location).parent.mkdir(parents=True, exist_ok=True)


def create_engine(settings: Settings) -> AsyncEngine:
    """Build the async engine, tuning pool behaviour per backend."""
    kwargs: dict[str, Any] = {"echo": settings.database_echo, "future": True}

    if settings.is_sqlite:
        ensure_sqlite_directory(settings)
        # SQLite's driver-level pooling adds nothing here and complicates teardown.
        kwargs["poolclass"] = NullPool
    else:
        kwargs["pool_size"] = settings.database_pool_size
        kwargs["max_overflow"] = settings.database_max_overflow
        kwargs["pool_pre_ping"] = True  # drop connections killed by a proxy/restart
        kwargs["pool_recycle"] = 1800

    engine = create_async_engine(settings.database_url, **kwargs)

    if settings.is_sqlite:
        event.listens_for(engine.sync_engine, "connect")(_sqlite_pragmas)

    logger.info(
        "database_engine_created",
        dialect=engine.dialect.name,
        pooled=not settings.is_sqlite,
    )
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,  # let handlers read attributes after commit
        autoflush=False,
    )


@asynccontextmanager
async def session_scope(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    """Transactional scope: commit on success, roll back on any exception.

    Used by workers and scripts. Request handlers get the same guarantee via
    the ``get_session`` dependency.
    """
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def check_database(engine: AsyncEngine) -> bool:
    """Liveness probe for the readiness endpoint."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error("database_healthcheck_failed", error=repr(exc))
        return False
    return True
