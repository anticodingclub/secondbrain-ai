"""Vector store contract."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class VectorRecord:
    """One chunk's vector plus the payload we can filter and cite on."""

    id: uuid.UUID
    vector: list[float]
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchHit:
    id: uuid.UUID
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchFilter:
    """Pre-filter applied inside the ANN search.

    ``owner_id`` is mandatory and not optional-by-accident: it is the tenant
    boundary. Filtering after retrieval would leak another user's documents into
    the top-k budget even when the results are later discarded.
    """

    owner_id: uuid.UUID
    document_ids: Sequence[uuid.UUID] | None = None
    collection_ids: Sequence[uuid.UUID] | None = None
    extensions: Sequence[str] | None = None
    language: str | None = None
    created_after: str | None = None
    created_before: str | None = None


class VectorStore(ABC):
    @abstractmethod
    async def ensure_collection(self, *, dimensions: int) -> None:
        """Create the collection and payload indexes if absent. Idempotent."""

    @abstractmethod
    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        """Insert or replace vectors by id, so re-indexing a document is safe."""

    @abstractmethod
    async def search(
        self,
        vector: Sequence[float],
        *,
        filters: SearchFilter,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[SearchHit]: ...

    @abstractmethod
    async def delete_by_document(self, document_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def delete_by_owner(self, owner_id: uuid.UUID) -> None: ...

    @abstractmethod
    async def count(self, *, owner_id: uuid.UUID | None = None) -> int: ...

    @abstractmethod
    async def health(self) -> bool: ...

    async def aclose(self) -> None:
        return None
