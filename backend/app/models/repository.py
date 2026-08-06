"""An imported code repository.

Distinct from `Collection` because a repository has state a folder does not:
the commit it was imported at, the branch it tracks, and whether it can be
re-synced. Documents still point at a `Collection`, so a repository owns one
and everything downstream — search filters, chat scoping, deletion — works
unchanged.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum as SAEnum
from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, JSONType, UTCDateTime, UUIDType

if TYPE_CHECKING:
    from app.models.collection import Collection
    from app.models.user import User


class RepositoryStatus(StrEnum):
    PENDING = "pending"
    CLONING = "cloning"
    IMPORTING = "importing"
    READY = "ready"
    FAILED = "failed"


class Repository(Entity):
    __tablename__ = "repositories"
    __table_args__ = (
        # One import per URL per user. Re-importing the same repository should
        # update it, not silently accumulate copies.
        UniqueConstraint("owner_id", "clone_url", name="uq_repositories_owner_url"),
        Index("ix_repositories_owner_status", "owner_id", "status"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUIDType, ForeignKey("collections.id", ondelete="SET NULL"), default=None
    )

    #: As given by the user, normalised. The clone URL and the display name are
    #: kept apart because a URL is not a name anyone wants to read.
    clone_url: Mapped[str] = mapped_column(String(1024))
    owner_name: Mapped[str] = mapped_column(String(255))
    repo_name: Mapped[str] = mapped_column(String(255))
    branch: Mapped[str | None] = mapped_column(String(255), default=None)

    #: The commit actually imported. This is what makes re-sync meaningful:
    #: without it there is no way to say whether anything changed.
    commit_sha: Mapped[str | None] = mapped_column(String(64), default=None)

    status: Mapped[RepositoryStatus] = mapped_column(
        SAEnum(RepositoryStatus, native_enum=False, length=32),
        default=RepositoryStatus.PENDING,
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, default=None)

    file_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    #: Files found but deliberately not imported — vendored trees, binaries,
    #: anything oversized. Surfaced so "why is my file missing?" has an answer.
    skipped_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")

    last_synced_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    repo_metadata: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)

    owner: Mapped[User] = relationship()
    collection: Mapped[Collection | None] = relationship()

    @property
    def full_name(self) -> str:
        return f"{self.owner_name}/{self.repo_name}"

    def __repr__(self) -> str:
        return f"<Repository {self.full_name} ({self.status})>"
