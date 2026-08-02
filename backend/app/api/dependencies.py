"""FastAPI dependency providers.

These are thin adapters from the container to the request scope. Route handlers
annotate the interface they need; they never construct it.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.container import Container
from app.services.embeddings import EmbeddingProvider
from app.services.vectorstore import VectorStore


def get_container(request: Request) -> Container:
    return request.app.state.container  # type: ignore[no-any-return]


def get_settings_dep(container: Annotated[Container, Depends(get_container)]) -> Settings:
    return container.settings


def get_vector_store(container: Annotated[Container, Depends(get_container)]) -> VectorStore:
    return container.vector_store


def get_embedding_provider(
    container: Annotated[Container, Depends(get_container)],
) -> EmbeddingProvider:
    return container.embedding_provider


async def get_session(
    container: Annotated[Container, Depends(get_container)],
) -> AsyncIterator[AsyncSession]:
    """One transaction per request: commit on success, roll back on any error.

    Handlers therefore never call ``commit()``. A handler that raises after a
    partial write leaves nothing behind.
    """
    session = container.session_factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


ContainerDep = Annotated[Container, Depends(get_container)]
SettingsDep = Annotated[Settings, Depends(get_settings_dep)]
SessionDep = Annotated[AsyncSession, Depends(get_session)]
VectorStoreDep = Annotated[VectorStore, Depends(get_vector_store)]
EmbeddingProviderDep = Annotated[EmbeddingProvider, Depends(get_embedding_provider)]
