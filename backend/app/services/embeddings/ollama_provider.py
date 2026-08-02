"""Ollama provider — embeddings over HTTP, zero Python ML dependencies.

Useful when Ollama is already running for chat: one model server, no torch in
the API image, and the model stays resident across restarts of this process.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence

import httpx

from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.core.retry import with_retry
from app.services.embeddings.base import EmbeddingProvider

logger = get_logger(__name__)


class OllamaEmbeddingProvider(EmbeddingProvider):
    def __init__(
        self,
        model_name: str = "nomic-embed-text",
        *,
        base_url: str = "http://localhost:11434",
        dimensions: int = 768,
        batch_size: int = 16,
        timeout: float = 120.0,
    ) -> None:
        self._model_name = model_name
        self._dimensions = dimensions
        self._batch_size = batch_size
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"), timeout=timeout)

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def _embed_one(self, text: str) -> list[float]:
        async def call() -> list[float]:
            try:
                response = await self._client.post(
                    "/api/embeddings", json={"model": self._model_name, "prompt": text}
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                # Normalise to a transient type so the shared retry policy applies.
                raise ConnectionError(f"Ollama embedding request failed: {exc}") from exc
            embedding = response.json().get("embedding")
            if not embedding:
                raise ExternalServiceError("Ollama returned an empty embedding.")
            return [float(value) for value in embedding]

        return await with_retry(call)  # type: ignore[no-any-return]

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float]] = []
        # Ollama's embeddings endpoint is single-text; bound the fan-out so we
        # do not overwhelm a laptop-sized model server.
        for start in range(0, len(texts), self._batch_size):
            window = texts[start : start + self._batch_size]
            results.extend(await asyncio.gather(*(self._embed_one(t) for t in window)))
        return results

    async def embed_query(self, text: str) -> list[float]:
        return await self._embed_one(text)

    async def warm_up(self) -> None:
        await self._embed_one("warm up")

    async def aclose(self) -> None:
        await self._client.aclose()
