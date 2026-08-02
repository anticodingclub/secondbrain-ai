"""System introspection — which providers this instance is actually running.

The frontend uses this to render the active model and to disable features (like
GPU-only reranking) that this deployment does not support.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app import __version__
from app.api.dependencies import ContainerDep

router = APIRouter(prefix="/system", tags=["system"])


class EmbeddingInfo(BaseModel):
    provider: str
    model: str
    dimensions: int


class VectorStoreInfo(BaseModel):
    backend: str
    mode: str
    collection: str


class SystemInfo(BaseModel):
    app_name: str
    version: str
    environment: str
    embedding: EmbeddingInfo
    vector_store: VectorStoreInfo
    llm_provider: str
    llm_model: str
    storage_backend: str


@router.get("", response_model=SystemInfo, summary="Active runtime configuration")
async def system_info(container: ContainerDep) -> SystemInfo:
    settings = container.settings
    return SystemInfo(
        app_name=settings.app_name,
        version=__version__,
        environment=settings.environment,
        embedding=EmbeddingInfo(
            provider=settings.embedding_provider,
            model=container.embedding_provider.model_name,
            dimensions=container.embedding_provider.dimensions,
        ),
        vector_store=VectorStoreInfo(
            backend="qdrant",
            mode="embedded" if settings.qdrant_is_embedded else "server",
            collection=settings.qdrant_collection,
        ),
        llm_provider=settings.llm_provider,
        llm_model=settings.llm_model,
        storage_backend=settings.storage_backend,
    )
