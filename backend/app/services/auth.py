"""Authentication orchestration.

Owns the rules; knows nothing about HTTP. The API layer turns the results into
responses and cookies.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.exceptions import AuthenticationError, ConflictError, InvalidSessionError
from app.core.logging import get_logger
from app.core.security import (
    TokenClaims,
    TokenType,
    create_token,
    decode_token,
    hash_password,
    needs_rehash,
    verify_password,
    waste_time_like_a_real_verification,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository, normalize_email

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    access_expires_in: int
    refresh_expires_at: datetime
    user: User


@dataclass(frozen=True, slots=True)
class ClientContext:
    """Non-authoritative request metadata, recorded for the security audit log."""

    user_agent: str | None = None
    ip_address: str | None = None


class AuthService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        users: UserRepository,
        refresh_tokens: RefreshTokenRepository,
        settings: Settings,
    ) -> None:
        self._session = session
        self._users = users
        self._refresh_tokens = refresh_tokens
        self._settings = settings

    async def _revoke_family_durably(self, family_id: uuid.UUID) -> None:
        """Revoke a token family and commit immediately.

        Services do not normally commit — the request owns the transaction.
        This is the deliberate exception: every caller here goes on to raise,
        and the request-scoped rollback would otherwise undo the revocation,
        leaving a security control that logs loudly and does nothing at all.
        """
        await self._refresh_tokens.revoke_family(family_id)
        await self._session.commit()

    # ── Registration ─────────────────────────────────────────────────────

    async def register(
        self, *, email: str, password: str, display_name: str, context: ClientContext
    ) -> IssuedTokens:
        normalized = normalize_email(email)

        if await self._users.email_exists(normalized):
            # Registration necessarily leaks whether an address is taken —
            # there is no way to create a duplicate account silently. Login and
            # password reset are where enumeration must be prevented.
            raise ConflictError("An account with that email already exists.")

        user = User(
            email=normalized,
            display_name=display_name.strip(),
            hashed_password=hash_password(password),
        )
        await self._users.add(user)
        logger.info("user_registered", user_id=str(user.id))

        return await self._issue_token_pair(user, context=context)

    # ── Login ────────────────────────────────────────────────────────────

    async def authenticate(
        self, *, email: str, password: str, context: ClientContext
    ) -> IssuedTokens:
        user = await self._users.get_by_email(email)

        if user is None:
            # Burn equivalent CPU so response time does not reveal that the
            # address is unregistered.
            waste_time_like_a_real_verification()
            raise AuthenticationError("Incorrect email or password.")

        if not verify_password(password, user.hashed_password):
            logger.warning("login_failed", user_id=str(user.id))
            raise AuthenticationError("Incorrect email or password.")

        if not user.is_active:
            raise AuthenticationError("This account has been deactivated.")

        # Transparently upgrade hashes written under older cost parameters.
        if needs_rehash(user.hashed_password):
            user.hashed_password = hash_password(password)
            logger.info("password_hash_upgraded", user_id=str(user.id))

        logger.info("login_succeeded", user_id=str(user.id))
        return await self._issue_token_pair(user, context=context)

    # ── Refresh ──────────────────────────────────────────────────────────

    async def refresh(self, *, refresh_token: str, context: ClientContext) -> IssuedTokens:
        """Rotate a refresh token, detecting replay.

        Presenting an already-consumed token means the same lineage is in two
        hands. We cannot tell the attacker from the victim, so both lose: the
        whole family is revoked and everyone re-authenticates.
        """
        # Every failure below is an InvalidSessionError: whatever the cause,
        # the cookie the client holds is unusable and must be discarded rather
        # than retried.
        try:
            claims = decode_token(
                refresh_token,
                secret_key=self._settings.secret_key,
                expected_type=TokenType.REFRESH,
            )
        except AuthenticationError as exc:
            raise InvalidSessionError(str(exc)) from exc

        stored = await self._refresh_tokens.get_by_jti(claims.jti)
        if stored is None:
            # Correctly signed but unknown to us — issued before a logout-all,
            # or forged by someone who obtained the signing key.
            logger.warning("refresh_token_unknown", jti=str(claims.jti))
            raise InvalidSessionError("The session is no longer valid.")

        if not stored.is_active:
            logger.error(
                "refresh_token_replay_detected",
                jti=str(stored.jti),
                family_id=str(stored.family_id),
                user_id=str(stored.user_id),
                ip_address=context.ip_address,
            )
            await self._revoke_family_durably(stored.family_id)
            raise InvalidSessionError("This session was revoked. Please sign in again.")

        if stored.expires_at <= datetime.now(UTC):
            raise InvalidSessionError("The session has expired.")

        user = await self._users.get(stored.user_id)
        if user is None or not user.is_active:
            await self._revoke_family_durably(stored.family_id)
            raise InvalidSessionError("This account is no longer active.")

        return await self._issue_token_pair(
            user, context=context, family_id=stored.family_id, rotating=stored
        )

    # ── Logout ───────────────────────────────────────────────────────────

    async def logout(self, *, refresh_token: str | None) -> None:
        """Revoke the presented session. Idempotent by design.

        A logout that errors because the token was already invalid would leave
        the client unable to clear its state, which is worse than a no-op.
        """
        if not refresh_token:
            return
        try:
            claims = decode_token(
                refresh_token,
                secret_key=self._settings.secret_key,
                expected_type=TokenType.REFRESH,
            )
        except AuthenticationError:
            return

        if (stored := await self._refresh_tokens.get_by_jti(claims.jti)) is not None:
            await self._refresh_tokens.revoke_family(stored.family_id)
            logger.info("logout", user_id=str(stored.user_id))

    async def logout_everywhere(self, *, user_id: uuid.UUID) -> int:
        revoked = await self._refresh_tokens.revoke_all_for_user(user_id)
        logger.info("logout_all_sessions", user_id=str(user_id), revoked=revoked)
        return revoked

    # ── Access-token verification ────────────────────────────────────────

    async def resolve_access_token(self, token: str) -> User:
        """Decode an access token and load its user.

        Access tokens are not checked against the database on every request —
        that would forfeit the point of a stateless token. Their short lifetime
        is the containment mechanism; the `is_active` check below is the one
        piece of freshness worth the lookup, since it is what makes a
        deactivated account stop working within the access-token window.
        """
        claims = decode_token(
            token, secret_key=self._settings.secret_key, expected_type=TokenType.ACCESS
        )
        user = await self._users.get(claims.subject)
        if user is None or not user.is_active:
            raise AuthenticationError("This account is no longer active.")
        return user

    # ── Internals ────────────────────────────────────────────────────────

    async def _issue_token_pair(
        self,
        user: User,
        *,
        context: ClientContext,
        family_id: uuid.UUID | None = None,
        rotating: RefreshToken | None = None,
    ) -> IssuedTokens:
        access_ttl = timedelta(minutes=self._settings.access_token_ttl_minutes)
        refresh_ttl = timedelta(days=self._settings.refresh_token_ttl_days)
        family = family_id or uuid.uuid4()

        access_token, _ = create_token(
            subject=user.id,
            token_type=TokenType.ACCESS,
            secret_key=self._settings.secret_key,
            expires_in=access_ttl,
        )
        refresh_token, refresh_claims = create_token(
            subject=user.id,
            token_type=TokenType.REFRESH,
            secret_key=self._settings.secret_key,
            expires_in=refresh_ttl,
            family_id=family,
        )

        await self._persist_refresh_token(user, refresh_claims, family, context)

        if rotating is not None:
            await self._refresh_tokens.mark_rotated(rotating, replaced_by=refresh_claims.jti)

        return IssuedTokens(
            access_token=access_token,
            refresh_token=refresh_token,
            access_expires_in=int(access_ttl.total_seconds()),
            refresh_expires_at=refresh_claims.expires_at,
            user=user,
        )

    async def _persist_refresh_token(
        self,
        user: User,
        claims: TokenClaims,
        family_id: uuid.UUID,
        context: ClientContext,
    ) -> None:
        await self._refresh_tokens.add(
            RefreshToken(
                jti=claims.jti,
                family_id=family_id,
                user_id=user.id,
                expires_at=claims.expires_at,
                user_agent=(context.user_agent or None) and context.user_agent[:512],
                ip_address=context.ip_address,
            )
        )
