"""Server-side record of issued refresh tokens.

A JWT alone cannot be revoked — that is the whole point of a stateless token,
and it is unacceptable for a 14-day credential. Persisting one row per issued
refresh token buys three things a bare JWT cannot give us: logout that actually
logs out, rotation, and replay detection.

**Rotation:** each refresh consumes its token and issues a new one. A stolen
token is therefore only useful until the legitimate client next refreshes.

**Reuse detection:** if an already-consumed token is presented again, either the
attacker or the victim is using a token the other one already spent. We cannot
tell which, so we revoke the entire `family_id` lineage and force a fresh login.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, String, true
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Entity, UTCDateTime, UUIDType

if TYPE_CHECKING:
    from app.models.user import User


class RefreshToken(Entity):
    __tablename__ = "refresh_tokens"
    __table_args__ = (
        Index("ix_refresh_tokens_user_family", "user_id", "family_id"),
        Index("ix_refresh_tokens_expires_at", "expires_at"),
    )

    #: The JWT's `jti`. Unique so a replayed token is caught by the database
    #: even if two requests race.
    jti: Mapped[uuid.UUID] = mapped_column(UUIDType, unique=True, index=True)
    #: Shared by every token descended from a single login.
    family_id: Mapped[uuid.UUID] = mapped_column(UUIDType, index=True)

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )

    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, default=None)
    #: Set when this token is rotated, so the audit trail shows the chain.
    replaced_by_jti: Mapped[uuid.UUID | None] = mapped_column(UUIDType, default=None)

    #: Recorded for the security log when a replay is detected; not used for auth.
    user_agent: Mapped[str | None] = mapped_column(String(512), default=None)
    ip_address: Mapped[str | None] = mapped_column(String(45), default=None)

    #: Denormalised so revoking a whole family is one UPDATE rather than a
    #: read-modify-write over every row.
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())

    user: Mapped[User] = relationship()

    def __repr__(self) -> str:
        return f"<RefreshToken {self.jti} active={self.is_active}>"
