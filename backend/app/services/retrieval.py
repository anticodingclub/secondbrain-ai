"""Finding the right passages.

Two retrievers, fused. Dense vector search understands meaning — it finds the
Dockerfile paragraph for "how do we build the container image" even though the
words differ. Keyword search understands *exactness* — it finds `AuthService`
or an order number, which an embedding blurs into every nearby identifier.

Neither is sufficient alone, and which one wins depends entirely on the query,
so the system cannot pick in advance. Fusing both and letting agreement decide
is what makes retrieval hold up across "where is my offer letter" and
"SECONDBRAIN_SECRET_KEY" in the same search box.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.document import Document, DocumentChunk
from app.services.embeddings import EmbeddingProvider
from app.services.vectorstore import SearchFilter, VectorStore

logger = get_logger(__name__)

#: How much a rank contributes in reciprocal rank fusion: 1 / (k + rank).
#:
#: 60 is the value from the original RRF paper and it is not arbitrary — it
#: flattens the curve enough that the difference between rank 1 and rank 2
#: does not swamp a document that both retrievers ranked moderately well.
#: Agreement between the two should beat a single retriever's confidence.
RRF_K = 60


@dataclass(frozen=True, slots=True)
class SearchHit:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    filename: str
    extension: str
    text: str
    score: float
    page_number: int | None = None
    section_title: str | None = None
    #: Which retrievers found this, for debugging why a result ranked where
    #: it did — the single most common question about any search system.
    matched_by: tuple[str, ...] = ()
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    limit: int = 10
    document_ids: Sequence[uuid.UUID] | None = None
    collection_id: uuid.UUID | None = None
    extensions: Sequence[str] | None = None
    #: Dense-only or keyword-only, for comparison and for queries where one is
    #: obviously right. Default fuses both.
    mode: str = "hybrid"
    metadata: dict[str, object] = field(default_factory=dict)


class RetrievalService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        embedder: EmbeddingProvider,
        vector_store: VectorStore,
    ) -> None:
        self._session = session
        self._embedder = embedder
        self._vectors = vector_store

    async def search(self, query: SearchQuery, *, owner_id: uuid.UUID) -> list[SearchHit]:
        text = query.text.strip()
        if not text:
            return []

        # Over-fetch from each retriever. Fusion needs depth to work with: a
        # chunk ranked 15th by one and 3rd by the other should be able to win,
        # which it cannot if only the top 10 of each are considered.
        depth = max(query.limit * 3, 30)

        dense: list[uuid.UUID] = []
        keyword: list[uuid.UUID] = []

        if query.mode in {"hybrid", "semantic"}:
            dense = await self._dense_search(text, owner_id=owner_id, query=query, limit=depth)
        if query.mode in {"hybrid", "keyword"}:
            keyword = await self._keyword_search(text, owner_id=owner_id, query=query, limit=depth)

        ranked = _reciprocal_rank_fusion({"semantic": dense, "keyword": keyword})
        if not ranked:
            return []

        top = ranked[: query.limit]
        hydrated = await self._hydrate([chunk_id for chunk_id, _, _ in top], owner_id=owner_id)

        hits: list[SearchHit] = []
        for chunk_id, score, sources in top:
            row = hydrated.get(chunk_id)
            if row is None:
                # Vector store and database disagree. Skipping is right: a hit
                # we cannot render or attribute is worse than one fewer result.
                logger.warning("search_hit_without_row", chunk_id=str(chunk_id))
                continue
            chunk, document = row
            hits.append(
                SearchHit(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    document_title=document.title,
                    filename=document.original_filename,
                    extension=document.extension,
                    text=chunk.content,
                    score=round(score, 6),
                    page_number=chunk.page_number,
                    section_title=chunk.section_title,
                    matched_by=sources,
                    snippet=make_snippet(chunk.content, text),
                )
            )
        return hits

    # ── Retrievers ───────────────────────────────────────────────────────

    async def _dense_search(
        self, text: str, *, owner_id: uuid.UUID, query: SearchQuery, limit: int
    ) -> list[uuid.UUID]:
        vector = await self._embedder.embed_query(text)
        results = await self._vectors.search(
            vector,
            filters=SearchFilter(
                owner_id=owner_id,
                document_ids=list(query.document_ids) if query.document_ids else None,
                extensions=list(query.extensions) if query.extensions else None,
            ),
            limit=limit,
        )
        return [result.id for result in results]

    async def _keyword_search(
        self, text: str, *, owner_id: uuid.UUID, query: SearchQuery, limit: int
    ) -> list[uuid.UUID]:
        """Term matching over chunk text.

        ILIKE rather than Postgres full-text search because the same code must
        run on SQLite in development, and a retriever that silently behaves
        differently between dev and production is worse than a simple one.
        Phase 10 can swap in `tsvector` behind this method; the fusion above
        does not care.
        """
        terms = _significant_terms(text)
        if not terms:
            return []

        statement = (
            select(DocumentChunk.id)
            .join(Document, Document.id == DocumentChunk.document_id)
            .where(DocumentChunk.owner_id == owner_id)
        )
        if query.document_ids:
            statement = statement.where(DocumentChunk.document_id.in_(list(query.document_ids)))
        if query.extensions:
            statement = statement.where(Document.extension.in_(list(query.extensions)))

        statement = statement.where(
            or_(*(DocumentChunk.content.ilike(f"%{term}%") for term in terms))
        ).limit(limit * 2)

        candidate_ids = list((await self._session.execute(statement)).scalars().all())
        if not candidate_ids:
            return []

        # ILIKE gives no ranking, so order by how many distinct terms a chunk
        # contains. A chunk matching every term beats one matching a single
        # common word.
        rows = (
            await self._session.execute(
                select(DocumentChunk.id, DocumentChunk.content).where(
                    DocumentChunk.id.in_(candidate_ids)
                )
            )
        ).all()

        scored = sorted(
            (
                (sum(term in content.lower() for term in terms), chunk_id)
                for chunk_id, content in rows
            ),
            key=lambda pair: pair[0],
            reverse=True,
        )
        return [chunk_id for _, chunk_id in scored[:limit]]

    async def _hydrate(
        self, chunk_ids: Sequence[uuid.UUID], *, owner_id: uuid.UUID
    ) -> dict[uuid.UUID, tuple[DocumentChunk, Document]]:
        if not chunk_ids:
            return {}

        # Scoped by owner again even though the vector store already filtered:
        # the tenant boundary should not rest on a second system having been
        # configured correctly.
        rows = (
            await self._session.execute(
                select(DocumentChunk, Document)
                .join(Document, Document.id == DocumentChunk.document_id)
                .where(
                    DocumentChunk.id.in_(list(chunk_ids)),
                    DocumentChunk.owner_id == owner_id,
                )
            )
        ).all()
        return {chunk.id: (chunk, document) for chunk, document in rows}


def _reciprocal_rank_fusion(
    rankings: dict[str, list[uuid.UUID]],
) -> list[tuple[uuid.UUID, float, tuple[str, ...]]]:
    """Combine ranked lists without needing comparable scores.

    Cosine similarity and a keyword match count are not on the same scale, and
    normalising them would mean inventing a conversion that has no meaning.
    RRF sidesteps this entirely by using only *position*, which both retrievers
    genuinely agree on.
    """
    scores: dict[uuid.UUID, float] = {}
    sources: dict[uuid.UUID, list[str]] = {}

    for name, ranking in rankings.items():
        for rank, chunk_id in enumerate(ranking, start=1):
            scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
            sources.setdefault(chunk_id, []).append(name)

    return sorted(
        ((chunk_id, score, tuple(sources[chunk_id])) for chunk_id, score in scores.items()),
        key=lambda item: item[1],
        reverse=True,
    )


#: Words too common to narrow anything. Kept deliberately short — an
#: aggressive stop list breaks real queries like "The Who" or "let it be".
_STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "have",
        "in",
        "is",
        "it",
        "its",
        "of",
        "on",
        "or",
        "that",
        "the",
        "to",
        "was",
        "were",
        "will",
        "with",
        "what",
        "where",
        "when",
        "how",
        "do",
        "does",
        "did",
        "i",
        "my",
        "me",
    ]
)


def _significant_terms(text: str) -> list[str]:
    terms = [
        term
        for term in re.findall(r"[\w'-]+", text.lower())
        if len(term) > 1 and term not in _STOP_WORDS
    ]
    # If the query was entirely stop words, searching for nothing returns
    # nothing; fall back to the raw words so the user gets *something*.
    return terms or re.findall(r"[\w'-]+", text.lower())


def make_snippet(content: str, query: str, *, width: int = 240) -> str:
    """A window of text centred on the first matching term.

    Returning the head of every chunk would show the same boilerplate for
    every result; the point of a snippet is to show *why* this one matched.
    """
    terms = _significant_terms(query)
    lowered = content.lower()

    position = next((index for index in (lowered.find(term) for term in terms) if index >= 0), -1)
    if position < 0:
        return content[:width].strip() + ("…" if len(content) > width else "")

    start = max(0, position - width // 3)
    end = min(len(content), start + width)
    snippet = content[start:end].strip()

    return f"{'…' if start > 0 else ''}{snippet}{'…' if end < len(content) else ''}"
