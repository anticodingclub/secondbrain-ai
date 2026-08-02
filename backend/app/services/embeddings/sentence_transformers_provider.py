"""sentence-transformers provider — the full-quality path (bge-large-en-v1.5).

Use when retrieval quality matters more than footprint, or when a GPU is
available. Same interface as the fastembed provider, so switching is a config
change plus a re-index.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.services.embeddings.base import EmbeddingProvider
from app.services.embeddings.fastembed_provider import BGE_QUERY_INSTRUCTION

logger = get_logger(__name__)


class SentenceTransformersProvider(EmbeddingProvider):
    def __init__(
        self,
        model_name: str = "BAAI/bge-large-en-v1.5",
        *,
        dimensions: int = 1024,
        batch_size: int = 32,
        device: str | None = None,
        cache_dir: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._device = device
        self._cache_dir = cache_dir
        self._model: Any | None = None
        self._lock = asyncio.Lock()

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def _get_model(self) -> Any:
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is not None:
                return self._model
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # pragma: no cover - depends on install extras
                raise ConfigurationError(
                    "sentence-transformers is not installed. Install it with: "
                    'pip install -e ".[embeddings-torch]"'
                ) from exc

            logger.info(
                "loading_embedding_model", model=self._model_name, runtime="sentence_transformers"
            )
            model = await asyncio.to_thread(
                SentenceTransformer,
                self._model_name,
                device=self._device,
                cache_folder=self._cache_dir,
            )
            actual = int(model.get_sentence_embedding_dimension())
            if actual != self._dimensions:
                # Fail loudly at load time; a silent mismatch surfaces later as
                # opaque Qdrant rejections during indexing.
                raise ConfigurationError(
                    f"{self._model_name} produces {actual}-d vectors but "
                    f"SECONDBRAIN_EMBEDDING_DIMENSIONS is {self._dimensions}."
                )
            logger.info("embedding_model_ready", model=self._model_name, dimensions=actual)
            self._model = model
            return model

    def _encode(self, model: Any, texts: list[str]) -> list[list[float]]:
        # Normalised vectors make cosine similarity equal to a dot product,
        # which is the cheaper operation for Qdrant to run.
        vectors: list[list[float]] = model.encode(
            texts,
            batch_size=self._batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        ).tolist()
        return vectors

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await self._get_model()
        return await asyncio.to_thread(self._encode, model, list(texts))

    async def embed_query(self, text: str) -> list[float]:
        model = await self._get_model()
        prefixed = f"{BGE_QUERY_INSTRUCTION}{text}" if "bge" in self._model_name.lower() else text
        vectors = await asyncio.to_thread(self._encode, model, [prefixed])
        return vectors[0]

    async def warm_up(self) -> None:
        await self._get_model()
