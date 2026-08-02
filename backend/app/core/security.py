"""Password hashing and JWT primitives.

Deliberately free of database and HTTP concerns so it can be unit-tested
exhaustively — this is the code where a subtle mistake is a security incident
rather than a bug report.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Final

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.exceptions import AuthenticationError
from app.core.logging import get_logger

logger = get_logger(__name__)

ALGORITHM: Final = "HS256"

#: Argon2id at the OWASP-recommended second-choice profile (46 MiB, t=1, p=1).
#: Memory cost is what makes GPU cracking expensive, so it is the parameter
#: worth spending on rather than iterations.
_hasher = PasswordHasher(time_cost=2, memory_cost=47104, parallelism=1, hash_len=32, salt_len=16)

#: Argon2 rejects longer inputs outright, and unbounded input is a trivial DoS
#: (hashing is intentionally expensive).
MAX_PASSWORD_BYTES: Final = 1024
MIN_PASSWORD_LENGTH: Final = 8


class TokenType(StrEnum):
    ACCESS = "access"
    REFRESH = "refresh"


@dataclass(frozen=True, slots=True)
class TokenClaims:
    """Decoded, validated JWT payload."""

    subject: uuid.UUID
    token_type: TokenType
    jti: uuid.UUID
    issued_at: datetime
    expires_at: datetime
    #: Groups every token descended from one login, so a detected replay can
    #: revoke the entire lineage rather than a single token.
    family_id: uuid.UUID | None = None


# ── Passwords ────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    _guard_password_length(password)
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    """Constant-time-ish verification. Never raises for a wrong password."""
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        return False
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    """True when a stored hash predates the current cost parameters.

    Lets us transparently upgrade a user's hash on their next successful login
    instead of leaving old weak hashes in the database forever.
    """
    try:
        return _hasher.check_needs_rehash(hashed)
    except InvalidHashError:
        return True


def _guard_password_length(password: str) -> None:
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password.encode("utf-8")) > MAX_PASSWORD_BYTES:
        raise ValueError("Password is too long.")


#: A real Argon2 digest of a throwaway value, used to burn the same CPU time on
#: a missing user as on a wrong password. Without it, response latency tells an
#: attacker which email addresses are registered.
DUMMY_HASH: Final = _hasher.hash("secondbrain-timing-equalizer")


def waste_time_like_a_real_verification() -> None:
    verify_password("not-the-password", DUMMY_HASH)


# ── Tokens ───────────────────────────────────────────────────────────────────


def create_token(
    *,
    subject: uuid.UUID,
    token_type: TokenType,
    secret_key: str,
    expires_in: timedelta,
    family_id: uuid.UUID | None = None,
    jti: uuid.UUID | None = None,
) -> tuple[str, TokenClaims]:
    """Mint a signed JWT and return it alongside its claims.

    The claims come back so the caller can persist the ``jti`` without decoding
    what it just encoded.
    """
    now = datetime.now(UTC)
    claims = TokenClaims(
        subject=subject,
        token_type=token_type,
        jti=jti or uuid.uuid4(),
        issued_at=now,
        expires_at=now + expires_in,
        family_id=family_id,
    )
    payload: dict[str, Any] = {
        "sub": str(claims.subject),
        "type": claims.token_type.value,
        "jti": str(claims.jti),
        "iat": int(claims.issued_at.timestamp()),
        "exp": int(claims.expires_at.timestamp()),
    }
    if claims.family_id is not None:
        payload["fam"] = str(claims.family_id)

    return jwt.encode(payload, secret_key, algorithm=ALGORITHM), claims


def decode_token(token: str, *, secret_key: str, expected_type: TokenType) -> TokenClaims:
    """Verify signature, expiry and token type.

    ``expected_type`` is not optional by oversight: without it a refresh token —
    which is long-lived and sits in a cookie — would be accepted as an access
    token, quietly turning a 30-minute credential into a 14-day one.
    """
    try:
        payload = jwt.decode(
            token,
            secret_key,
            algorithms=[ALGORITHM],
            options={"require": ["sub", "exp", "iat", "jti", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("The token has expired.") from exc
    except jwt.InvalidTokenError as exc:
        # Covers bad signature, malformed input, missing claims and `alg: none`.
        raise AuthenticationError("The token is invalid.") from exc

    if payload.get("type") != expected_type.value:
        logger.warning(
            "token_type_mismatch", expected=expected_type.value, received=payload.get("type")
        )
        raise AuthenticationError("The token is not valid for this operation.")

    try:
        return TokenClaims(
            subject=uuid.UUID(payload["sub"]),
            token_type=expected_type,
            jti=uuid.UUID(payload["jti"]),
            issued_at=datetime.fromtimestamp(payload["iat"], tz=UTC),
            expires_at=datetime.fromtimestamp(payload["exp"], tz=UTC),
            family_id=uuid.UUID(payload["fam"]) if payload.get("fam") else None,
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise AuthenticationError("The token is malformed.") from exc
