"""Refresh token persistence."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, update

from app.models.refresh_token import RefreshToken
from app.repositories.base import SQLAlchemyRepository


class RefreshTokenRepository(SQLAlchemyRepository[RefreshToken]):
    model = RefreshToken

    async def get_by_jti(self, jti: uuid.UUID) -> RefreshToken | None:
        return await self.find_one_by(jti=jti)

    async def revoke_family(self, family_id: uuid.UUID) -> int:
        """Kill every token descended from one login.

        Used on logout-everywhere and, critically, on replay detection: once a
        consumed token reappears we cannot distinguish the attacker from the
        victim, so the only safe move is to invalidate the whole lineage.
        """
        return await self.execute_returning_rowcount(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.is_active.is_(True))
            .values(is_active=False, revoked_at=datetime.now(UTC))
        )

    async def revoke_all_for_user(self, user_id: uuid.UUID) -> int:
        return await self.execute_returning_rowcount(
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.is_active.is_(True))
            .values(is_active=False, revoked_at=datetime.now(UTC))
        )

    async def mark_rotated(self, token: RefreshToken, *, replaced_by: uuid.UUID) -> None:
        token.is_active = False
        token.revoked_at = datetime.now(UTC)
        token.replaced_by_jti = replaced_by
        await self.session.flush()

    async def purge_expired(self, *, now: datetime | None = None) -> int:
        """Housekeeping: drop rows that can no longer authenticate anything."""
        cutoff = now or datetime.now(UTC)
        return await self.execute_returning_rowcount(
            delete(RefreshToken).where(RefreshToken.expires_at < cutoff)
        )
