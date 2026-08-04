"""Document persistence.

Every method takes an ``owner_id``. Tenant scoping is not something callers can
forget here, because there is no unscoped way to ask.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import Select, func, select

from app.models.document import Document, DocumentStatus
from app.repositories.base import SQLAlchemyRepository


class DocumentRepository(SQLAlchemyRepository[Document]):
    model = Document

    async def get_for_owner(
        self, document_id: uuid.UUID, *, owner_id: uuid.UUID
    ) -> Document | None:
        """Fetch one document, or None if it is missing **or** not theirs.

        Collapsing "not found" and "not yours" is deliberate: distinguishing
        them tells an attacker which document ids exist.
        """
        return await self.find_one_by(id=document_id, owner_id=owner_id)

    async def find_by_content_hash(
        self, content_hash: str, *, owner_id: uuid.UUID
    ) -> Document | None:
        return await self.find_one_by(owner_id=owner_id, content_hash=content_hash)

    def _filtered(
        self,
        *,
        owner_id: uuid.UUID,
        status: DocumentStatus | None = None,
        extensions: Sequence[str] | None = None,
        collection_id: uuid.UUID | None = None,
        search: str | None = None,
        created_after: datetime | None = None,
        created_before: datetime | None = None,
    ) -> Select[tuple[Document]]:
        """The shared WHERE clause, so list and count can never disagree."""
        statement = select(Document).where(Document.owner_id == owner_id)

        if status is not None:
            statement = statement.where(Document.status == status)
        if extensions:
            statement = statement.where(Document.extension.in_(list(extensions)))
        if collection_id is not None:
            statement = statement.where(Document.collection_id == collection_id)
        if created_after is not None:
            statement = statement.where(Document.created_at >= created_after)
        if created_before is not None:
            statement = statement.where(Document.created_at <= created_before)
        if search:
            # Title/filename substring match. Real full-text search over
            # content arrives with the hybrid retriever in Phase 6; this is
            # just "find the file I named X".
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                Document.title.ilike(pattern) | Document.original_filename.ilike(pattern)
            )
        return statement

    async def list_for_owner(
        self,
        *,
        owner_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
        **filters: object,
    ) -> Sequence[Document]:
        statement = (
            self._filtered(owner_id=owner_id, **filters)  # type: ignore[arg-type]
            .order_by(Document.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return (await self.session.execute(statement)).scalars().all()

    async def count_for_owner(self, *, owner_id: uuid.UUID, **filters: object) -> int:
        inner = self._filtered(owner_id=owner_id, **filters).subquery()  # type: ignore[arg-type]
        result = await self.session.execute(select(func.count()).select_from(inner))
        return int(result.scalar_one())

    async def total_bytes_for_owner(self, owner_id: uuid.UUID) -> int:
        result = await self.session.execute(
            select(func.coalesce(func.sum(Document.size_bytes), 0)).where(
                Document.owner_id == owner_id
            )
        )
        return int(result.scalar_one())
