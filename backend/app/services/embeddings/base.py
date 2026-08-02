"""Embedding provider contract.

Retrieval quality, cost and offline capability all hinge on this one choice, and
it is the choice most likely to change. Everything downstream therefore depends
on this interface rather than on a specific model runtime.

Asymmetric models such as BGE expect an instruction prefix on the *query* but
not on the *document*; the split between ``embed_documents`` and ``embed_query``
puts that detail inside the provider where it belongs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence


class EmbeddingProvider(ABC):
    """Turns text into dense vectors."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        """Identifier persisted alongside each chunk.

        Vectors from different models are not comparable, so re-embedding must
        be able to find exactly which chunks are stale.
        """

    @property
    @abstractmethod
    def dimensions(self) -> int:
        """Vector width. Must match the Qdrant collection or writes are rejected."""

    @abstractmethod
    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed corpus text. Returns one vector per input, in order."""

    @abstractmethod
    async def embed_query(self, text: str) -> list[float]:
        """Embed a search query."""

    async def warm_up(self) -> None:
        """Optional: pay model-load cost at startup instead of on first request."""
        return None

    async def aclose(self) -> None:
        """Optional: release sockets, threads or GPU memory."""
        return None
