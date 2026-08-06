"""Qdrant vector store.

Runs embedded (in-process, local path) for development and against a server or
cluster in production — the same class, switched by whether ``QDRANT_URL`` is
set. Qdrant is the choice here because it supports payload *pre*-filtering
inside the HNSW traversal, which is what makes per-user isolation and metadata
filters correct rather than approximate.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any

from qdrant_client import AsyncQdrantClient, models

from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger
from app.core.retry import with_retry
from app.services.vectorstore.base import SearchFilter, SearchHit, VectorRecord, VectorStore

logger = get_logger(__name__)

#: Payload fields we filter on need an index, otherwise Qdrant falls back to a
#: full scan of the payload for every query.
INDEXED_PAYLOAD_FIELDS: dict[str, models.PayloadSchemaType] = {
    "owner_id": models.PayloadSchemaType.KEYWORD,
    "document_id": models.PayloadSchemaType.KEYWORD,
    "collection_id": models.PayloadSchemaType.KEYWORD,
    "extension": models.PayloadSchemaType.KEYWORD,
    "language": models.PayloadSchemaType.KEYWORD,
    "created_at": models.PayloadSchemaType.DATETIME,
}


class QdrantVectorStore(VectorStore):
    def __init__(
        self,
        *,
        collection: str,
        url: str | None = None,
        api_key: str | None = None,
        path: Path | None = None,
        upsert_batch_size: int = 256,
    ) -> None:
        if url:
            self._client = AsyncQdrantClient(url=url, api_key=api_key, prefer_grpc=False)
            self._mode = "server"
        else:
            if path is None:
                raise ValueError("Either url or path must be provided for Qdrant.")
            path.mkdir(parents=True, exist_ok=True)
            self._client = AsyncQdrantClient(path=str(path))
            self._mode = "embedded"

        self._collection = collection
        self._batch_size = upsert_batch_size
        self._ensured = False
        self._lock = asyncio.Lock()

    @property
    def mode(self) -> str:
        return self._mode

    async def ensure_collection(self, *, dimensions: int) -> None:
        async with self._lock:
            if self._ensured:
                return
            if not await self._client.collection_exists(self._collection):
                await self._client.create_collection(
                    collection_name=self._collection,
                    vectors_config=models.VectorParams(
                        size=dimensions,
                        distance=models.Distance.COSINE,
                        # Keep vectors on disk: at millions of chunks the RAM
                        # cost of holding them all resident is the binding
                        # constraint, while the HNSW graph stays in memory.
                        on_disk=True,
                    ),
                    hnsw_config=models.HnswConfigDiff(m=16, ef_construct=100),
                    optimizers_config=models.OptimizersConfigDiff(default_segment_number=2),
                )
                logger.info(
                    "qdrant_collection_created",
                    collection=self._collection,
                    dimensions=dimensions,
                    mode=self._mode,
                )

            # Embedded Qdrant filters by scanning payloads and ignores indexes,
            # so creating them there only emits warnings.
            if self._mode == "server":
                for field, schema in INDEXED_PAYLOAD_FIELDS.items():
                    # Already-indexed fields raise; the call is meant to be idempotent.
                    with suppress(Exception):
                        await self._client.create_payload_index(
                            collection_name=self._collection,
                            field_name=field,
                            field_schema=schema,
                        )
            self._ensured = True

    def _build_filter(self, filters: SearchFilter) -> models.Filter:
        must: list[models.Condition] = [
            models.FieldCondition(
                key="owner_id", match=models.MatchValue(value=str(filters.owner_id))
            )
        ]
        if filters.document_ids:
            must.append(
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchAny(any=[str(d) for d in filters.document_ids]),
                )
            )
        if filters.collection_ids:
            must.append(
                models.FieldCondition(
                    key="collection_id",
                    match=models.MatchAny(any=[str(c) for c in filters.collection_ids]),
                )
            )
        if filters.extensions:
            must.append(
                models.FieldCondition(
                    key="extension",
                    match=models.MatchAny(any=[e.lower() for e in filters.extensions]),
                )
            )
        if filters.language:
            must.append(
                models.FieldCondition(
                    key="language", match=models.MatchValue(value=filters.language)
                )
            )
        if filters.created_after or filters.created_before:
            must.append(
                models.FieldCondition(
                    key="created_at",
                    range=models.DatetimeRange(
                        gte=filters.created_after, lte=filters.created_before
                    ),
                )
            )
        return models.Filter(must=must)

    async def upsert(self, records: Sequence[VectorRecord]) -> None:
        if not records:
            return
        for start in range(0, len(records), self._batch_size):
            window = records[start : start + self._batch_size]
            points = [
                models.PointStruct(id=str(r.id), vector=r.vector, payload=r.payload) for r in window
            ]

            async def call(points: list[models.PointStruct] = points) -> None:
                await self._client.upsert(
                    collection_name=self._collection, points=points, wait=True
                )

            await with_retry(call, exceptions=(Exception,))
        logger.debug("qdrant_upserted", collection=self._collection, count=len(records))

    async def search(
        self,
        vector: Sequence[float],
        *,
        filters: SearchFilter,
        limit: int = 10,
        score_threshold: float | None = None,
    ) -> list[SearchHit]:
        try:
            response = await self._client.query_points(
                collection_name=self._collection,
                query=list(vector),
                query_filter=self._build_filter(filters),
                limit=limit,
                score_threshold=score_threshold,
                with_payload=True,
            )
        except Exception as exc:
            logger.error("qdrant_search_failed", error=repr(exc))
            raise ExternalServiceError("Vector search failed.") from exc

        return [
            SearchHit(id=uuid.UUID(str(p.id)), score=float(p.score), payload=dict(p.payload or {}))
            for p in response.points
        ]

    async def _delete_where(self, key: str, value: str) -> None:
        await self._client.delete(
            collection_name=self._collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[models.FieldCondition(key=key, match=models.MatchValue(value=value))]
                )
            ),
            wait=True,
        )

    async def drop_collection(self) -> None:
        """Delete the collection and forget that it was ensured.

        Clearing `_ensured` matters: the next `ensure_collection` must
        actually recreate it rather than trusting a cached flag about a
        collection that no longer exists.
        """
        async with self._lock:
            if await self._client.collection_exists(self._collection):
                await self._client.delete_collection(self._collection)
            self._ensured = False
        logger.info("qdrant_collection_dropped", collection=self._collection)

    async def delete_by_document(self, document_id: uuid.UUID) -> None:
        await self._delete_where("document_id", str(document_id))

    async def delete_by_owner(self, owner_id: uuid.UUID) -> None:
        await self._delete_where("owner_id", str(owner_id))

    async def count(self, *, owner_id: uuid.UUID | None = None) -> int:
        count_filter: models.Filter | None = None
        if owner_id is not None:
            count_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="owner_id", match=models.MatchValue(value=str(owner_id))
                    )
                ]
            )
        result = await self._client.count(
            collection_name=self._collection, count_filter=count_filter, exact=False
        )
        return int(result.count)

    async def health(self) -> bool:
        try:
            await self._client.get_collections()
        except Exception as exc:
            logger.error("qdrant_healthcheck_failed", error=repr(exc))
            return False
        return True

    async def aclose(self) -> None:
        await self._client.close()

    def collection_info(self) -> dict[str, Any]:
        return {"collection": self._collection, "mode": self._mode}
