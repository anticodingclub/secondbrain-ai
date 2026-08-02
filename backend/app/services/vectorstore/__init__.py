"""Vector storage behind a single interface."""

from app.core.config import Settings
from app.services.vectorstore.base import SearchFilter, SearchHit, VectorRecord, VectorStore
from app.services.vectorstore.qdrant_store import QdrantVectorStore


def build_vector_store(settings: Settings) -> VectorStore:
    return QdrantVectorStore(
        collection=settings.qdrant_collection,
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        path=settings.resolve_path(settings.qdrant_path),
    )


__all__ = [
    "QdrantVectorStore",
    "SearchFilter",
    "SearchHit",
    "VectorRecord",
    "VectorStore",
    "build_vector_store",
]
