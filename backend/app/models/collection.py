"""Collections: user-defined groupings that scope search and chat.

Self-referential so a synced local folder tree or a repository's directory
structure maps onto the same entity as a hand-made group.
"""

from __future__ import annotations

import uuid
from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, UUIDType

if TYPE_CHECKING:
    from app.models.document import Document
    from app.models.user import User


class CollectionKind(StrEnum):
    MANUAL = "manual"
    SYNCED_FOLDER = "synced_folder"
    GITHUB_REPO = "github_repo"


class Collection(Entity):
    __tablename__ = "collections"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("collections.id", ondelete="CASCADE"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, default=None)
    kind: Mapped[CollectionKind] = mapped_column(
        SAEnum(CollectionKind, native_enum=False, length=32), default=CollectionKind.MANUAL
    )
    #: Filesystem path or clone URL for synced kinds; NULL for manual collections.
    source_uri: Mapped[str | None] = mapped_column(String(1024), default=None)

    owner: Mapped[User] = relationship(back_populates="collections")
    parent: Mapped[Collection | None] = relationship(remote_side="Collection.id")
    documents: Mapped[list[Document]] = relationship(back_populates="collection")

    def __repr__(self) -> str:
        return f"<Collection {self.name} ({self.kind})>"
