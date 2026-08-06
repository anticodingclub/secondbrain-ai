"""Dashboard statistics."""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.dependencies import AnalyticsServiceDep, CurrentUser, VectorStoreDep
from app.models.document import DocumentStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


class CountedResponse(BaseModel):
    label: str
    count: int


class RecentSearchResponse(BaseModel):
    query: str
    hit_count: int
    took_ms: int
    created_at: datetime


class RecentDocumentResponse(BaseModel):
    id: uuid.UUID
    title: str
    extension: str
    size_bytes: int
    status: DocumentStatus
    created_at: datetime


class DashboardResponse(BaseModel):
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
    indexing_progress: float
    by_extension: list[CountedResponse]
    by_status: list[CountedResponse]
    top_queries: list[CountedResponse]
    recent_searches: list[RecentSearchResponse]
    recent_documents: list[RecentDocumentResponse]


@router.get("", response_model=DashboardResponse, summary="Your library at a glance")
async def dashboard(
    current_user: CurrentUser,
    analytics: AnalyticsServiceDep,
    vector_store: VectorStoreDep,
) -> DashboardResponse:
    # Counted from Qdrant rather than inferred from chunk rows: the two stores
    # drifting apart is exactly the failure worth surfacing, and a dashboard
    # that derived one from the other could never show it.
    vector_count = await vector_store.count(owner_id=current_user.id)

    stats = await analytics.dashboard(owner_id=current_user.id, vector_count=vector_count)

    return DashboardResponse(
        document_count=stats.document_count,
        indexed_count=stats.indexed_count,
        failed_count=stats.failed_count,
        pending_count=stats.pending_count,
        chunk_count=stats.chunk_count,
        vector_count=stats.vector_count,
        total_bytes=stats.total_bytes,
        conversation_count=stats.conversation_count,
        message_count=stats.message_count,
        search_count=stats.search_count,
        searches_last_7_days=stats.searches_last_7_days,
        median_search_ms=stats.median_search_ms,
        indexing_progress=stats.indexing_progress,
        by_extension=[CountedResponse(label=c.label, count=c.count) for c in stats.by_extension],
        by_status=[CountedResponse(label=c.label, count=c.count) for c in stats.by_status],
        top_queries=[CountedResponse(label=c.label, count=c.count) for c in stats.top_queries],
        recent_searches=[
            RecentSearchResponse(
                query=s.query,
                hit_count=s.hit_count,
                took_ms=s.took_ms,
                created_at=s.created_at,
            )
            for s in stats.recent_searches
        ],
        recent_documents=[
            RecentDocumentResponse(
                id=d.id,
                title=d.title,
                extension=d.extension,
                size_bytes=d.size_bytes,
                status=d.status,
                created_at=d.created_at,
            )
            for d in stats.recent_documents
        ],
    )
