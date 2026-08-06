"""User account. Owns every other entity — the tenant boundary."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String, false, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity

if TYPE_CHECKING:
    from app.models.collection import Collection
    from app.models.document import Document


class User(Entity):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(120))
    # Argon2id digest, populated in Phase 2. Never a plaintext or reversible value.
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    is_superuser: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    documents: Mapped[list[Document]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )
    collections: Mapped[list[Collection]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<User {self.email}>"
