"""Password hashing and JWT primitives.

Weighted towards the failure paths: a bug here is a security incident, and the
happy path is the one case that gets exercised by hand anyway.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.exceptions import AuthenticationError
from app.core.security import (
    ALGORITHM,
    MAX_PASSWORD_BYTES,
    TokenType,
    create_token,
    decode_token,
    hash_password,
    verify_password,
)

SECRET = "test-secret-key-for-signing-tokens"
OTHER_SECRET = "a-completely-different-secret-key"


# ── Passwords ────────────────────────────────────────────────────────────────


def test_hash_is_not_the_password() -> None:
    hashed = hash_password("correct horse battery staple")
    assert "correct horse" not in hashed
    assert hashed.startswith("$argon2id$")


def test_same_password_hashes_differently_each_time() -> None:
    """Distinct salts; identical passwords must not produce identical digests."""
    assert hash_password("hunter2hunter2") != hash_password("hunter2hunter2")


def test_verify_accepts_the_right_password() -> None:
    assert verify_password("hunter2hunter2", hash_password("hunter2hunter2"))


@pytest.mark.parametrize(
    "wrong",
    ["hunter2hunter3", "Hunter2Hunter2", "hunter2hunter2 ", "", "hunter2hunter22"],
)
def test_verify_rejects_wrong_passwords(wrong: str) -> None:
    assert not verify_password(wrong, hash_password("hunter2hunter2"))


def test_verify_returns_false_for_a_corrupt_hash_instead_of_raising() -> None:
    # A malformed row in the database must not 500 the login endpoint.
    assert not verify_password("anything", "not-a-real-argon2-hash")


def test_rejects_passwords_below_the_minimum_length() -> None:
    with pytest.raises(ValueError, match="at least"):
        hash_password("short")


def test_rejects_absurdly_long_passwords() -> None:
    """Unbounded input into a deliberately slow hash is a free DoS."""
    with pytest.raises(ValueError, match="too long"):
        hash_password("a" * (MAX_PASSWORD_BYTES + 1))


def test_verify_rejects_overlong_input_without_hashing_it() -> None:
    assert not verify_password("a" * (MAX_PASSWORD_BYTES + 1), hash_password("hunter2hunter2"))


def test_unicode_passwords_round_trip() -> None:
    password = "пароль-🔐-密码"
    assert verify_password(password, hash_password(password))


# ── Tokens ───────────────────────────────────────────────────────────────────


def test_access_token_round_trips() -> None:
    user_id = uuid.uuid4()
    token, claims = create_token(
        subject=user_id,
        token_type=TokenType.ACCESS,
        secret_key=SECRET,
        expires_in=timedelta(minutes=30),
    )

    decoded = decode_token(token, secret_key=SECRET, expected_type=TokenType.ACCESS)
    assert decoded.subject == user_id
    assert decoded.jti == claims.jti
    assert decoded.token_type is TokenType.ACCESS


def test_refresh_token_carries_its_family() -> None:
    family = uuid.uuid4()
    token, _ = create_token(
        subject=uuid.uuid4(),
        token_type=TokenType.REFRESH,
        secret_key=SECRET,
        expires_in=timedelta(days=14),
        family_id=family,
    )

    assert (
        decode_token(token, secret_key=SECRET, expected_type=TokenType.REFRESH).family_id == family
    )


def test_each_token_gets_a_unique_jti() -> None:
    def mint() -> uuid.UUID:
        _, claims = create_token(
            subject=uuid.uuid4(),
            token_type=TokenType.ACCESS,
            secret_key=SECRET,
            expires_in=timedelta(minutes=5),
        )
        return claims.jti

    assert len({mint() for _ in range(10)}) == 10


def test_a_refresh_token_is_not_accepted_as_an_access_token() -> None:
    """The critical confusion: a 14-day cookie credential must never be usable
    as a 30-minute API credential."""
    token, _ = create_token(
        subject=uuid.uuid4(),
        token_type=TokenType.REFRESH,
        secret_key=SECRET,
        expires_in=timedelta(days=14),
        family_id=uuid.uuid4(),
    )

    with pytest.raises(AuthenticationError, match="not valid for this operation"):
        decode_token(token, secret_key=SECRET, expected_type=TokenType.ACCESS)


def test_an_access_token_is_not_accepted_as_a_refresh_token() -> None:
    token, _ = create_token(
        subject=uuid.uuid4(),
        token_type=TokenType.ACCESS,
        secret_key=SECRET,
        expires_in=timedelta(minutes=30),
    )

    with pytest.raises(AuthenticationError):
        decode_token(token, secret_key=SECRET, expected_type=TokenType.REFRESH)


def test_expired_token_is_rejected() -> None:
    token, _ = create_token(
        subject=uuid.uuid4(),
        token_type=TokenType.ACCESS,
        secret_key=SECRET,
        expires_in=timedelta(seconds=-1),
    )

    with pytest.raises(AuthenticationError, match="expired"):
        decode_token(token, secret_key=SECRET, expected_type=TokenType.ACCESS)


def test_token_signed_with_another_key_is_rejected() -> None:
    token, _ = create_token(
        subject=uuid.uuid4(),
        token_type=TokenType.ACCESS,
        secret_key=OTHER_SECRET,
        expires_in=timedelta(minutes=30),
    )

    with pytest.raises(AuthenticationError, match="invalid"):
        decode_token(token, secret_key=SECRET, expected_type=TokenType.ACCESS)


def test_tampered_payload_is_rejected() -> None:
    token, _ = create_token(
        subject=uuid.uuid4(),
        token_type=TokenType.ACCESS,
        secret_key=SECRET,
        expires_in=timedelta(minutes=30),
    )
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload[:-4]}AAAA.{signature}"

    with pytest.raises(AuthenticationError):
        decode_token(tampered, secret_key=SECRET, expected_type=TokenType.ACCESS)


def test_alg_none_token_is_rejected() -> None:
    """The classic JWT bypass: an unsigned token claiming `alg: none`."""
    forged = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "jti": str(uuid.uuid4()),
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        key="",
        algorithm="none",
    )

    with pytest.raises(AuthenticationError):
        decode_token(forged, secret_key=SECRET, expected_type=TokenType.ACCESS)


def test_token_missing_required_claims_is_rejected() -> None:
    incomplete = jwt.encode({"sub": str(uuid.uuid4())}, SECRET, algorithm=ALGORITHM)

    with pytest.raises(AuthenticationError):
        decode_token(incomplete, secret_key=SECRET, expected_type=TokenType.ACCESS)


def test_token_with_non_uuid_subject_is_rejected() -> None:
    malformed = jwt.encode(
        {
            "sub": "not-a-uuid",
            "type": "access",
            "jti": str(uuid.uuid4()),
            "iat": int(datetime.now(UTC).timestamp()),
            "exp": int((datetime.now(UTC) + timedelta(hours=1)).timestamp()),
        },
        SECRET,
        algorithm=ALGORITHM,
    )

    with pytest.raises(AuthenticationError, match="malformed"):
        decode_token(malformed, secret_key=SECRET, expected_type=TokenType.ACCESS)


@pytest.mark.parametrize("garbage", ["", "abc", "a.b.c", "....", "Bearer sometoken"])
def test_garbage_input_is_rejected_cleanly(garbage: str) -> None:
    with pytest.raises(AuthenticationError):
        decode_token(garbage, secret_key=SECRET, expected_type=TokenType.ACCESS)
