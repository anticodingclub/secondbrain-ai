"""A record of each search, for the dashboard.

Queries are stored in full. That is a deliberate privacy decision worth being
explicit about: search history is among the most revealing data a system can
hold, and this one is single-tenant and local-first, so the trade is that the
user gets "what do I keep looking for?" and nobody else ever sees it. A hosted
multi-tenant deployment should revisit this — hashing or truncating instead —
which is why the column is isolated in its own table rather than mixed into
anything else.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Entity, UUIDType

if TYPE_CHECKING:
    pass


class SearchEvent(Entity):
    __tablename__ = "search_events"
    __table_args__ = (Index("ix_search_events_owner_created", "owner_id", "created_at"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    #: Truncated at the column width rather than rejected: an over-long query
    #: is still worth counting, and failing to log must never fail a search.
    query: Mapped[str] = mapped_column(String(512))
    #: Normalised (lowercased, collapsed whitespace) so "OAuth" and "oauth  "
    #: aggregate together in "most frequent queries".
    normalized_query: Mapped[str] = mapped_column(String(512), index=True)

    hit_count: Mapped[int] = mapped_column(Integer, default=0)
    took_ms: Mapped[int] = mapped_column(Integer, default=0)
    mode: Mapped[str] = mapped_column(String(16), default="hybrid")

    #: The winning document, which is what "most found documents" counts.
    #: Nullable because a search can legitimately return nothing.
    top_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("documents.id", ondelete="SET NULL"), default=None
    )

    def __repr__(self) -> str:
        return f"<SearchEvent {self.query!r} hits={self.hit_count}>"
