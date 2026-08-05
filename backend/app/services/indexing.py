"""Making a parsed document searchable.

Chunks it, embeds the chunks, and writes them to both stores — text and
anchors to Postgres, vectors to Qdrant, joined by `DocumentChunk.id`.

The ordering here is the part worth understanding. Postgres is written first
and Qdrant second, because a chunk row without a vector is merely not-yet-
searchable, while a vector without a row is a search hit that cannot be
rendered, cited or attributed to an owner. One of those degrades; the other
returns nonsense.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.repositories.chunk import ChunkRepository
from app.repositories.document import DocumentRepository
from app.services.chunking import Chunk, ChunkingStrategy, normalise_whitespace
from app.services.embeddings import EmbeddingProvider
from app.services.parsing.base import TextBlock
from app.services.parsing.pipeline import ParsingService
from app.services.vectorstore import VectorRecord, VectorStore

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IndexingResult:
    document_id: uuid.UUID
    chunk_count: int
    skipped: bool = False
    reason: str | None = None


class IndexingService:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        parsing: ParsingService,
        chunker: ChunkingStrategy,
        embedder: EmbeddingProvider,
        vector_store: VectorStore,
        settings: Settings,
    ) -> None:
        self._session_factory = session_factory
        self._parsing = parsing
        self._chunker = chunker
        self._embedder = embedder
        self._vectors = vector_store
        self._settings = settings

    async def index_document(
        self, document_id: uuid.UUID, *, owner_id: uuid.UUID
    ) -> IndexingResult:
        """Chunk, embed and index one document.

        Runs as a background task, so it records failure on the document
        rather than raising into a void where nothing would report it.
        """
        async with self._session_factory() as session:
            documents = DocumentRepository(session)
            document = await documents.get_for_owner(document_id, owner_id=owner_id)
            if document is None:
                logger.warning("index_target_missing", document_id=str(document_id))
                return IndexingResult(document_id, 0, skipped=True, reason="missing")

            if document.status not in _INDEXABLE_STATUSES:
                return IndexingResult(
                    document_id, 0, skipped=True, reason=f"status is {document.status}"
                )

            parsed = await self._parsing.load_blocks(document)
            if parsed is None or parsed.is_empty:
                # Nothing to search. Terminal rather than failed: an image
                # without OCR is a legitimate document, just not a searchable
                # one, and marking it failed would imply a fixable error.
                document.status = DocumentStatus.INDEXED
                document.chunk_count = 0
                await session.commit()
                return IndexingResult(document_id, 0, skipped=True, reason="no text")

            document.status = DocumentStatus.CHUNKING
            await session.commit()

        cleaned = [_normalised(block) for block in parsed.blocks]
        chunks = self._chunker.split([block for block in cleaned if block.text])

        if not chunks:
            await self._finalise(document_id, owner_id, chunk_count=0)
            return IndexingResult(document_id, 0, skipped=True, reason="no chunks")

        try:
            await self._embed_and_store(document_id, owner_id, chunks)
        except Exception as exc:
            logger.exception("indexing_failed", document_id=str(document_id))
            await self._record_failure(document_id, owner_id, str(exc))
            return IndexingResult(document_id, 0, skipped=True, reason=str(exc))

        await self._finalise(document_id, owner_id, chunk_count=len(chunks))
        logger.info("document_indexed", document_id=str(document_id), chunks=len(chunks))
        return IndexingResult(document_id, len(chunks))

    async def remove_document(self, document_id: uuid.UUID, *, owner_id: uuid.UUID) -> None:
        """Drop a document's vectors. Rows cascade from the document itself."""
        del owner_id  # ownership is verified before this is ever reached
        await self._vectors.delete_by_document(document_id)

    # ── Internals ────────────────────────────────────────────────────────

    async def _embed_and_store(
        self, document_id: uuid.UUID, owner_id: uuid.UUID, chunks: list[Chunk]
    ) -> None:
        async with self._session_factory() as session:
            documents = DocumentRepository(session)
            document = await documents.get_for_owner(document_id, owner_id=owner_id)
            if document is None:
                raise NotFoundError("Document disappeared during indexing.")

            document.status = DocumentStatus.EMBEDDING
            rows = [
                DocumentChunk(
                    document_id=document_id,
                    owner_id=owner_id,
                    ordinal=chunk.ordinal,
                    content=chunk.text,
                    token_count=chunk.approximate_tokens,
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    char_start=chunk.char_start,
                    char_end=chunk.char_end,
                    chunk_metadata=chunk.metadata,
                )
                for chunk in chunks
            ]
            await ChunkRepository(session).replace_for_document(document_id, rows)

            # Committed before embedding so the ids are stable and durable:
            # the vector payload references them, and a crash mid-embedding
            # must not leave Qdrant pointing at rows that were rolled back.
            await session.commit()

            stored = [(row.id, row.content, row.ordinal) for row in rows]
            extension = document.extension
            collection_id = document.collection_id

        # Any previous vectors for this document are removed first, so a
        # re-index that produces fewer chunks does not leave the surplus
        # searchable.
        await self._vectors.delete_by_document(document_id)

        batch_size = self._settings.index_batch_size
        for start in range(0, len(stored), batch_size):
            batch = stored[start : start + batch_size]
            vectors = await self._embedder.embed_documents([text for _, text, _ in batch])

            await self._vectors.upsert(
                [
                    VectorRecord(
                        id=chunk_id,
                        vector=vector,
                        payload={
                            "owner_id": str(owner_id),
                            "document_id": str(document_id),
                            "extension": extension,
                            "collection_id": str(collection_id) if collection_id else None,
                            "ordinal": ordinal,
                            "text": text,
                        },
                    )
                    for (chunk_id, text, ordinal), vector in zip(batch, vectors, strict=True)
                ]
            )

        # Recorded per chunk so a later model change can find stale vectors
        # rather than forcing a full re-index of everything.
        async with self._session_factory() as session:
            chunks_repo = ChunkRepository(session)
            for row in await chunks_repo.list_for_document(document_id, owner_id=owner_id):
                row.embedding_model = self._embedder.model_name
            await session.commit()

    async def _finalise(
        self, document_id: uuid.UUID, owner_id: uuid.UUID, *, chunk_count: int
    ) -> None:
        async with self._session_factory() as session:
            documents = DocumentRepository(session)
            document = await documents.get_for_owner(document_id, owner_id=owner_id)
            if document is None:
                return
            document.status = DocumentStatus.INDEXED
            document.chunk_count = chunk_count
            document.error_message = None
            await session.commit()

    async def _record_failure(
        self, document_id: uuid.UUID, owner_id: uuid.UUID, message: str
    ) -> None:
        async with self._session_factory() as session:
            documents = DocumentRepository(session)
            document = await documents.get_for_owner(document_id, owner_id=owner_id)
            if document is None:
                return
            document.status = DocumentStatus.FAILED
            document.error_message = f"Indexing failed: {message}"[:1000]
            await session.commit()


#: Only these may be indexed.
#:
#: FAILED is deliberately absent. Indexing runs immediately after parsing, and
#: a document that failed to parse has no text — the "nothing to index" branch
#: would mark it INDEXED and erase the error message explaining why it is
#: empty. The user would see a document that claims to be searchable and
#: returns nothing, with no way to find out what went wrong.
#:
#: Reparse still recovers such a document: parsing runs first, and on success
#: moves it to PARSED before indexing looks at it.
#:
#: CHUNKING and EMBEDDING are included so a run interrupted midway can be
#: retried; INDEXED so re-indexing an up-to-date document is allowed.
_INDEXABLE_STATUSES = {
    DocumentStatus.PARSED,
    DocumentStatus.CHUNKING,
    DocumentStatus.EMBEDDING,
    DocumentStatus.INDEXED,
}


def _normalised(block: TextBlock) -> TextBlock:
    """Tidy whitespace before chunking.

    PDF extraction in particular produces ragged spacing that inflates chunk
    sizes and embeds as noise.
    """
    return TextBlock(
        text=normalise_whitespace(block.text),
        page_number=block.page_number,
        section_title=block.section_title,
        heading_level=block.heading_level,
        metadata=block.metadata,
    )


def document_is_searchable(document: Document) -> bool:
    return document.status is DocumentStatus.INDEXED and document.chunk_count > 0
