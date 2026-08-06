"""Configuration that must fail loudly rather than quietly.

A misconfigured production deployment is not a runtime inconvenience. Booting
with the placeholder signing key means every session token in existence can be
forged by anyone who has read this repository — and the only symptom is that
everything works perfectly.

So these are checked at startup, where the failure is a refusal to boot with a
message naming the variable. Discovering it later means discovering it from a
breach.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings

PLACEHOLDER_KEY = "change-me-in-production-this-value-is-not-secret"
REAL_KEY = "a-genuinely-random-48-byte-value-from-secrets-token-urlsafe"

POSTGRES_URL = "postgresql+asyncpg://user:pw@db:5432/secondbrain"


def production(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.PRODUCTION,
        "secret_key": REAL_KEY,
        "database_url": POSTGRES_URL,
        **overrides,
    }
    return Settings(**values)  # type: ignore[arg-type]


def test_production_refuses_the_placeholder_secret_key() -> None:
    """The single most consequential misconfiguration there is."""
    with pytest.raises(ValidationError) as error:
        production(secret_key=PLACEHOLDER_KEY)

    assert "secret" in str(error.value).lower()


def test_production_refuses_sqlite() -> None:
    """SQLite has one writer. Background indexing running alongside live
    queries would serialise onto it and then start timing out."""
    with pytest.raises(ValidationError) as error:
        production(database_url="sqlite+aiosqlite:///./data/app.db")

    assert "sqlite" in str(error.value).lower()


def test_production_accepts_a_correct_configuration() -> None:
    settings = production()

    assert settings.environment is Environment.PRODUCTION
    assert not settings.is_sqlite


def test_development_tolerates_both() -> None:
    """The defaults have to work with zero setup, or nobody can run it."""
    settings = Settings(environment=Environment.DEVELOPMENT)

    assert settings.secret_key == PLACEHOLDER_KEY
    assert settings.is_sqlite


def test_cookies_require_https_in_production_only() -> None:
    """A `secure` cookie is dropped over plain HTTP, so development and tests
    must not set it — and production must."""
    assert production().cookie_secure is True
    assert Settings(environment=Environment.DEVELOPMENT).cookie_secure is False
    assert Settings(environment=Environment.TEST).cookie_secure is False


def test_a_short_secret_key_is_refused() -> None:
    """A key short enough to brute-force is no better than the placeholder."""
    with pytest.raises(ValidationError):
        production(secret_key="short")
