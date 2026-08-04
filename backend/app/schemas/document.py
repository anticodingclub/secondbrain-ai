"""Document request/response contracts."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from app.models.document import DocumentStatus, SourceType

ItemT = TypeVar("ItemT")


class Page(BaseModel, Generic[ItemT]):
    """Offset pagination.

    `total` is returned so the UI can render "showing 20 of 1,340" without a
    second round trip; it costs one extra COUNT, which is cheap next to the
    alternative of the client guessing.
    """

    items: list[ItemT]
    total: int
    limit: int
    offset: int

    @property
    def has_more(self) -> bool:
        return self.offset + len(self.items) < self.total


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    original_filename: str
    mime_type: str
    extension: str
    size_bytes: int
    content_hash: str
    status: DocumentStatus
    source_type: SourceType
    collection_id: uuid.UUID | None
    error_message: str | None
    page_count: int | None
    word_count: int | None
    chunk_count: int
    language: str | None
    doc_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class UploadResponse(BaseModel):
    document: DocumentResponse
    #: Lets the UI say "already in your library" rather than implying a second
    #: copy was made.
    was_duplicate: bool


class DocumentFilters(BaseModel):
    """Query parameters for listing documents."""

    status: DocumentStatus | None = None
    extension: list[str] | None = Field(default=None, description="Repeatable.")
    collection_id: uuid.UUID | None = None
    search: str | None = Field(default=None, max_length=256)
    created_after: datetime | None = None
    created_before: datetime | None = None
    limit: Annotated[int, Field(ge=1, le=100)] = 50
    offset: Annotated[int, Field(ge=0)] = 0


class StorageUsageResponse(BaseModel):
    document_count: int
    total_bytes: int
    #: The server's configured ceiling, so the client does not hardcode it.
    max_upload_bytes: int
