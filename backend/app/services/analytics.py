"""Aggregates for the dashboard.

Everything here is scoped to one owner and computed on demand. At personal
scale — tens of thousands of documents — these are indexed aggregates over a
few thousand rows, and a caching layer would add staleness and invalidation
bugs to solve a problem that does not exist yet.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import Executable, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models.conversation import ChatMessage, Conversation
from app.models.document import Document, DocumentChunk, DocumentStatus
from app.models.search_event import SearchEvent

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Counted:
    label: str
    count: int


@dataclass(frozen=True, slots=True)
class RecentSearch:
    query: str
    hit_count: int
    took_ms: int
    created_at: datetime


@dataclass(frozen=True, slots=True)
class RecentDocument:
    id: uuid.UUID
    title: str
    extension: str
    size_bytes: int
    status: DocumentStatus
    created_at: datetime


@dataclass(frozen=True, slots=True)
class DashboardStats:
    document_count: int
    indexed_count: int
    failed_count: int
    pending_count: int
    chunk_count: int
    vector_count: int
    total_bytes: int
    conversation_count: int
    message_count: int
    search_count: int
    searches_last_7_days: int
    median_search_ms: int
    by_extension: Sequence[Counted] = field(default_factory=list)
    by_status: Sequence[Counted] = field(default_factory=list)
    top_queries: Sequence[Counted] = field(default_factory=list)
    recent_searches: Sequence[RecentSearch] = field(default_factory=list)
    recent_documents: Sequence[RecentDocument] = field(default_factory=list)

    @property
    def indexing_progress(self) -> float:
        """Share of documents that are searchable, 0-1."""
        if self.document_count == 0:
            return 1.0
        return round(self.indexed_count / self.document_count, 4)


def normalize_query(query: str) -> str:
    """Fold trivial variations so "OAuth" and "oauth  " aggregate together."""
    return re.sub(r"\s+", " ", query.strip().lower())[:512]


class AnalyticsService:
    def __init__(self, *, session: AsyncSession) -> None:
        self._session = session

    async def record_search(
        self,
        *,
        owner_id: uuid.UUID,
        query: str,
        hit_count: int,
        took_ms: int,
        mode: str,
        top_document_id: uuid.UUID | None,
    ) -> None:
        """Log one search.

        Never raises. Analytics is a nice-to-have, and a failure to record a
        search must not fail the search itself — the user asked a question,
        not for bookkeeping.
        """
        try:
            self._session.add(
                SearchEvent(
                    owner_id=owner_id,
                    query=query[:512],
                    normalized_query=normalize_query(query),
                    hit_count=hit_count,
                    took_ms=took_ms,
                    mode=mode,
                    top_document_id=top_document_id,
                )
            )
            await self._session.flush()
        except Exception as exc:
            logger.warning("search_event_not_recorded", error=str(exc))

    async def dashboard(self, *, owner_id: uuid.UUID, vector_count: int) -> DashboardStats:
        counts = await self._document_counts(owner_id)
        searches = await self._search_stats(owner_id)

        return DashboardStats(
            document_count=counts["total"],
            indexed_count=counts["indexed"],
            failed_count=counts["failed"],
            pending_count=counts["pending"],
            chunk_count=await self._scalar(
                select(func.count())
                .select_from(DocumentChunk)
                .where(DocumentChunk.owner_id == owner_id)
            ),
            vector_count=vector_count,
            total_bytes=await self._scalar(
                select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
                    Document.owner_id == owner_id
                )
            ),
            conversation_count=await self._scalar(
                select(func.count())
                .select_from(Conversation)
                .where(Conversation.owner_id == owner_id)
            ),
            message_count=await self._scalar(
                select(func.count())
                .select_from(ChatMessage)
                .where(ChatMessage.owner_id == owner_id)
            ),
            search_count=searches["total"],
            searches_last_7_days=searches["recent"],
            median_search_ms=searches["median_ms"],
            by_extension=await self._by_extension(owner_id),
            by_status=await self._by_status(owner_id),
            top_queries=await self._top_queries(owner_id),
            recent_searches=await self._recent_searches(owner_id),
            recent_documents=await self._recent_documents(owner_id),
        )

    # ── Internals ────────────────────────────────────────────────────────

    async def _scalar(self, statement: Executable) -> int:
        result = await self._session.execute(statement)
        return int(result.scalar_one() or 0)

    async def _document_counts(self, owner_id: uuid.UUID) -> dict[str, int]:
        rows = (
            await self._session.execute(
                select(Document.status, func.count())
                .where(Document.owner_id == owner_id)
                .group_by(Document.status)
            )
        ).all()

        by_status: dict[DocumentStatus, int] = {}
        for status, count in rows:
            by_status[status] = count

        # Anything not yet indexed and not failed is in flight, whichever
        # stage it happens to be at — the user does not care which.
        in_flight = sum(
            count
            for status, count in by_status.items()
            if status not in {DocumentStatus.INDEXED, DocumentStatus.FAILED}
        )
        return {
            "total": sum(by_status.values()),
            "indexed": by_status.get(DocumentStatus.INDEXED, 0),
            "failed": by_status.get(DocumentStatus.FAILED, 0),
            "pending": in_flight,
        }

    async def _by_extension(self, owner_id: uuid.UUID) -> list[Counted]:
        rows = (
            await self._session.execute(
                select(Document.extension, func.count())
                .where(Document.owner_id == owner_id)
                .group_by(Document.extension)
                .order_by(desc(func.count()))
                .limit(10)
            )
        ).all()
        return [Counted(label=extension, count=count) for extension, count in rows]

    async def _by_status(self, owner_id: uuid.UUID) -> list[Counted]:
        rows = (
            await self._session.execute(
                select(Document.status, func.count())
                .where(Document.owner_id == owner_id)
                .group_by(Document.status)
                .order_by(desc(func.count()))
            )
        ).all()
        return [Counted(label=str(status), count=count) for status, count in rows]

    async def _search_stats(self, owner_id: uuid.UUID) -> dict[str, int]:
        total = await self._scalar(
            select(func.count()).select_from(SearchEvent).where(SearchEvent.owner_id == owner_id)
        )
        recent = await self._scalar(
            select(func.count())
            .select_from(SearchEvent)
            .where(
                SearchEvent.owner_id == owner_id,
                SearchEvent.created_at >= datetime.now(UTC) - timedelta(days=7),
            )
        )

        # Median rather than mean: one cold-start search that loaded the
        # embedding model would drag an average into meaninglessness.
        durations = list(
            (
                await self._session.execute(
                    select(SearchEvent.took_ms)
                    .where(SearchEvent.owner_id == owner_id)
                    .order_by(SearchEvent.took_ms)
                )
            )
            .scalars()
            .all()
        )
        median = durations[len(durations) // 2] if durations else 0

        return {"total": total, "recent": recent, "median_ms": int(median)}

    async def _top_queries(self, owner_id: uuid.UUID) -> list[Counted]:
        rows = (
            await self._session.execute(
                select(SearchEvent.normalized_query, func.count())
                .where(SearchEvent.owner_id == owner_id)
                .group_by(SearchEvent.normalized_query)
                .order_by(desc(func.count()))
                .limit(8)
            )
        ).all()
        return [Counted(label=query, count=count) for query, count in rows]

    async def _recent_searches(self, owner_id: uuid.UUID) -> list[RecentSearch]:
        rows = (
            (
                await self._session.execute(
                    select(SearchEvent)
                    .where(SearchEvent.owner_id == owner_id)
                    .order_by(SearchEvent.created_at.desc())
                    .limit(8)
                )
            )
            .scalars()
            .all()
        )
        return [
            RecentSearch(
                query=event.query,
                hit_count=event.hit_count,
                took_ms=event.took_ms,
                created_at=event.created_at,
            )
            for event in rows
        ]

    async def _recent_documents(self, owner_id: uuid.UUID) -> list[RecentDocument]:
        rows = (
            (
                await self._session.execute(
                    select(Document)
                    .where(Document.owner_id == owner_id)
                    .order_by(Document.created_at.desc())
                    .limit(6)
                )
            )
            .scalars()
            .all()
        )
        return [
            RecentDocument(
                id=document.id,
                title=document.title or document.original_filename,
                extension=document.extension,
                size_bytes=document.size_bytes,
                status=document.status,
                created_at=document.created_at,
            )
            for document in rows
        ]
