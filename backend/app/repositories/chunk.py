"""Chunk persistence."""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import delete, func, select

from app.models.document import DocumentChunk
from app.repositories.base import SQLAlchemyRepository


class ChunkRepository(SQLAlchemyRepository[DocumentChunk]):
    model = DocumentChunk

    async def replace_for_document(
        self, document_id: uuid.UUID, chunks: Sequence[DocumentChunk]
    ) -> Sequence[DocumentChunk]:
        """Swap a document's chunks wholesale.

        Delete-then-insert rather than diffing: re-indexing happens because
        the text or the chunking parameters changed, which invalidates every
        ordinal anyway. A diff would be more code for a case that does not
        arise, and would risk leaving stale chunks behind.
        """
        await self.delete_for_document(document_id)
        if chunks:
            await self.add_all(chunks)
        return chunks

    async def delete_for_document(self, document_id: uuid.UUID) -> int:
        return await self.execute_returning_rowcount(
            delete(DocumentChunk).where(DocumentChunk.document_id == document_id)
        )

    async def list_for_document(
        self, document_id: uuid.UUID, *, owner_id: uuid.UUID
    ) -> Sequence[DocumentChunk]:
        result = await self.session.execute(
            select(DocumentChunk)
            .where(
                DocumentChunk.document_id == document_id,
                DocumentChunk.owner_id == owner_id,
            )
            .order_by(DocumentChunk.ordinal)
        )
        return result.scalars().all()

    async def get_many_for_owner(
        self, chunk_ids: Sequence[uuid.UUID], *, owner_id: uuid.UUID
    ) -> Sequence[DocumentChunk]:
        """Hydrate chunks returned by vector search.

        Scoped by owner even though the vector store already filtered: the
        tenant boundary should not depend on a second system having been
        configured correctly.
        """
        if not chunk_ids:
            return []
        result = await self.session.execute(
            select(DocumentChunk).where(
                DocumentChunk.id.in_(list(chunk_ids)),
                DocumentChunk.owner_id == owner_id,
            )
        )
        return result.scalars().all()

    async def count_for_owner(self, owner_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.owner_id == owner_id)
        )
        return int(result.scalar_one())
