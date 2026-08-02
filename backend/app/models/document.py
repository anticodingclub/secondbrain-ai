"""Documents and their chunks.

A ``Document`` is the unit a user recognises ("my offer letter"). A
``DocumentChunk`` is the unit retrieval operates on. Chunk *text* and metadata
live in Postgres while the *vector* lives in Qdrant, joined by
``DocumentChunk.id``: relational storage gives us cheap exact filters, joins and
citations, and Qdrant gives us ANN search. Duplicating either side would
guarantee they drift.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy import Enum as SAEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, JSONType, UUIDType

if TYPE_CHECKING:
    from app.models.collection import Collection
    from app.models.user import User


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PARSING = "parsing"
    CHUNKING = "chunking"
    EMBEDDING = "embedding"
    INDEXED = "indexed"
    FAILED = "failed"


class SourceType(StrEnum):
    UPLOAD = "upload"
    FOLDER_SYNC = "folder_sync"
    GITHUB = "github"
    URL = "url"


class Document(Entity):
    __tablename__ = "documents"
    __table_args__ = (
        # Content-hash dedupe is per user: two people may legitimately own the
        # same PDF, but one person should not pay to index it twice.
        UniqueConstraint("owner_id", "content_hash", name="uq_documents_owner_content_hash"),
        Index("ix_documents_owner_status", "owner_id", "status"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("collections.id", ondelete="SET NULL"), index=True, default=None
    )

    title: Mapped[str] = mapped_column(String(512))
    original_filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(32), index=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    #: SHA-256 of the raw bytes — drives dedupe and change detection on re-sync.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType, native_enum=False, length=32), default=SourceType.UPLOAD
    )
    #: Storage key, not a filesystem path — the same value addresses local disk
    #: today and an S3 object later.
    storage_key: Mapped[str] = mapped_column(String(1024))
    source_uri: Mapped[str | None] = mapped_column(String(1024), default=None)

    status: Mapped[DocumentStatus] = mapped_column(
        SAEnum(DocumentStatus, native_enum=False, length=32),
        default=DocumentStatus.PENDING,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    page_count: Mapped[int | None] = mapped_column(Integer, default=None)
    word_count: Mapped[int | None] = mapped_column(Integer, default=None)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    language: Mapped[str | None] = mapped_column(String(16), default=None, index=True)

    #: Parser-specific extras (PDF author, repo commit sha, EXIF, ...). Schemaless
    #: on purpose: every parser surfaces different fields and we do not want a
    #: migration each time we add one.
    doc_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    owner: Mapped[User] = relationship(back_populates="documents")
    collection: Mapped[Collection | None] = relationship(back_populates="documents")
    chunks: Mapped[list[DocumentChunk]] = relationship(
        back_populates="document", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Document {self.title} ({self.status})>"


class DocumentChunk(Entity):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ordinal", name="uq_document_chunks_document_ordinal"),
        Index("ix_document_chunks_owner_document", "owner_id", "document_id"),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    #: Denormalised from the parent document so search can filter by tenant
    #: without a join on the hot path.
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    ordinal: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    # ── Citation anchors (feature 14) ────────────────────────────────────
    page_number: Mapped[int | None] = mapped_column(Integer, default=None)
    section_title: Mapped[str | None] = mapped_column(String(512), default=None)
    char_start: Mapped[int | None] = mapped_column(Integer, default=None)
    char_end: Mapped[int | None] = mapped_column(Integer, default=None)

    #: Set once the vector is live in Qdrant. NULL means "written to Postgres but
    #: not yet searchable", which is exactly the state a crashed indexing run
    #: leaves behind and which the reconciliation worker looks for.
    embedding_model: Mapped[str | None] = mapped_column(String(128), default=None)

    chunk_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    document: Mapped[Document] = relationship(back_populates="chunks")

    def __repr__(self) -> str:
        return f"<DocumentChunk doc={self.document_id} #{self.ordinal}>"
