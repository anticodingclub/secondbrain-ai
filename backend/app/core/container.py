"""Composition root.

Every expensive, long-lived object is constructed here exactly once and handed
to consumers through FastAPI's dependency system. Concrete classes are named in
this file and nowhere else, which is what keeps the rest of the codebase
depending on interfaces — and makes swapping Qdrant for another store, or
fastembed for bge-large, a one-file change.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.logging import get_logger
from app.db.session import create_engine, create_session_factory
from app.services.embeddings import EmbeddingProvider, build_embedding_provider
from app.services.storage import ObjectStorage, build_object_storage
from app.services.vectorstore import VectorStore, build_vector_store

logger = get_logger(__name__)


@dataclass(slots=True)
class Container:
    settings: Settings
    engine: AsyncEngine
    session_factory: async_sessionmaker[AsyncSession]
    vector_store: VectorStore
    embedding_provider: EmbeddingProvider
    object_storage: ObjectStorage

    @classmethod
    def build(cls, settings: Settings) -> Container:
        engine = create_engine(settings)
        return cls(
            settings=settings,
            engine=engine,
            session_factory=create_session_factory(engine),
            vector_store=build_vector_store(settings),
            embedding_provider=build_embedding_provider(settings),
            object_storage=build_object_storage(settings),
        )

    async def startup(self) -> None:
        """Bring dependencies to a ready state before traffic is accepted."""
        # Fail here rather than on the first upload if the path is unwritable.
        self.settings.storage_path.mkdir(parents=True, exist_ok=True)
        await self.vector_store.ensure_collection(dimensions=self.embedding_provider.dimensions)
        logger.info(
            "container_started",
            embedding_provider=self.settings.embedding_provider,
            embedding_model=self.embedding_provider.model_name,
            dimensions=self.embedding_provider.dimensions,
            qdrant_mode="embedded" if self.settings.qdrant_is_embedded else "server",
        )

    async def shutdown(self) -> None:
        """Release resources in reverse order of acquisition."""
        await self.embedding_provider.aclose()
        await self.vector_store.aclose()
        await self.engine.dispose()
        logger.info("container_stopped")
