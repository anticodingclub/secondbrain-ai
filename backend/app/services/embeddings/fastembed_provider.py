"""fastembed provider — ONNX runtime, no PyTorch.

The default. A quantised bge-small is ~130 MB against ~4 GB for the
sentence-transformers + torch stack, and on CPU (where this app actually runs
for most users) ONNX is several times faster. Quality is close enough that the
retrieval pipeline can be built and tuned before committing to bge-large.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.services.embeddings.base import EmbeddingProvider

logger = get_logger(__name__)

#: BGE is trained with this instruction on the query side only. Omitting it
#: measurably degrades retrieval; adding it to documents also degrades it.
BGE_QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "


class FastEmbedProvider(EmbeddingProvider):
    def __init__(
        self,
        model_name: str = "BAAI/bge-small-en-v1.5",
        *,
        dimensions: int = 384,
        batch_size: int = 32,
        cache_dir: str | None = None,
    ) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._batch_size = batch_size
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
        """Load lazily and exactly once, even under concurrent first requests."""
        if self._model is not None:
            return self._model
        async with self._lock:
            if self._model is not None:
                return self._model
            try:
                from fastembed import TextEmbedding
            except ImportError as exc:  # pragma: no cover - depends on install extras
                raise ConfigurationError(
                    "fastembed is not installed. Install it with: "
                    'pip install -e ".[embeddings-fast]"'
                ) from exc

            logger.info("loading_embedding_model", model=self._model_name, runtime="fastembed")
            self._model = await asyncio.to_thread(
                TextEmbedding, model_name=self._model_name, cache_dir=self._cache_dir
            )
            logger.info("embedding_model_ready", model=self._model_name)
            return self._model

    def _encode(self, model: Any, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in model.embed(texts, batch_size=self._batch_size)]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        model = await self._get_model()
        # ONNX inference is CPU-bound and releases the GIL; a worker thread keeps
        # the event loop free to serve other requests.
        return await asyncio.to_thread(self._encode, model, list(texts))

    async def embed_query(self, text: str) -> list[float]:
        model = await self._get_model()
        prefixed = f"{BGE_QUERY_INSTRUCTION}{text}" if "bge" in self._model_name.lower() else text
        vectors = await asyncio.to_thread(self._encode, model, [prefixed])
        return vectors[0]

    async def warm_up(self) -> None:
        await self._get_model()
