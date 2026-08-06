"""Search over the user's own documents."""

from __future__ import annotations

import time
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.api.dependencies import AnalyticsServiceDep, CurrentUser, RetrievalServiceDep
from app.services.retrieval import SearchQuery

router = APIRouter(prefix="/search", tags=["search"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=1000)
    limit: Annotated[int, Field(ge=1, le=50)] = 10
    #: Scope to specific documents — "chat with this one file".
    document_ids: list[uuid.UUID] | None = None
    collection_id: uuid.UUID | None = None
    extensions: list[str] | None = None
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid"


class SearchHitResponse(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    filename: str
    extension: str
    text: str
    snippet: str
    score: float
    page_number: int | None
    section_title: str | None
    #: Which retrievers matched. Surfaced because "why did this rank here?" is
    #: the first question anyone asks of a search system.
    matched_by: list[str]


class SearchResponse(BaseModel):
    query: str
    hits: list[SearchHitResponse]
    total: int
    took_ms: int


@router.post("", response_model=SearchResponse, summary="Search your documents")
async def search(
    payload: SearchRequest,
    current_user: CurrentUser,
    retrieval: RetrievalServiceDep,
    analytics: AnalyticsServiceDep,
) -> SearchResponse:
    started = time.perf_counter()

    hits = await retrieval.search(
        SearchQuery(
            text=payload.query,
            limit=payload.limit,
            document_ids=payload.document_ids,
            collection_id=payload.collection_id,
            extensions=payload.extensions,
            mode=payload.mode,
        ),
        owner_id=current_user.id,
    )
    took_ms = int((time.perf_counter() - started) * 1000)

    # Recorded for the dashboard. Never raises — the user asked a question,
    # not for bookkeeping, and a logging failure must not fail their search.
    await analytics.record_search(
        owner_id=current_user.id,
        query=payload.query,
        hit_count=len(hits),
        took_ms=took_ms,
        mode=payload.mode,
        top_document_id=hits[0].document_id if hits else None,
    )

    return SearchResponse(
        query=payload.query,
        hits=[
            SearchHitResponse(
                chunk_id=hit.chunk_id,
                document_id=hit.document_id,
                document_title=hit.document_title,
                filename=hit.filename,
                extension=hit.extension,
                text=hit.text,
                snippet=hit.snippet,
                score=hit.score,
                page_number=hit.page_number,
                section_title=hit.section_title,
                matched_by=list(hit.matched_by),
            )
            for hit in hits
        ],
        total=len(hits),
        took_ms=took_ms,
    )
