from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Environment, Settings


def test_defaults_target_zero_install_development() -> None:
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    assert settings.is_sqlite
    assert settings.qdrant_is_embedded
    assert settings.environment is Environment.DEVELOPMENT


def test_qdrant_is_server_mode_when_url_present() -> None:
    settings = Settings(_env_file=None, qdrant_url="http://localhost:6333")  # type: ignore[call-arg]
    assert not settings.qdrant_is_embedded


def test_log_level_is_normalised() -> None:
    assert Settings(_env_file=None, log_level="debug").log_level == "DEBUG"  # type: ignore[call-arg]


def test_invalid_log_level_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, log_level="verbose")  # type: ignore[call-arg]


def test_production_rejects_the_placeholder_secret_key() -> None:
    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment=Environment.PRODUCTION,
            database_url="postgresql+asyncpg://u:p@db:5432/sb",
        )


def test_production_rejects_sqlite() -> None:
    with pytest.raises(ValidationError, match="SQLite"):
        Settings(  # type: ignore[call-arg]
            _env_file=None,
            environment=Environment.PRODUCTION,
            secret_key="a-real-secret",
            database_url="sqlite+aiosqlite:///./data/x.db",
        )


def test_production_accepts_a_valid_configuration() -> None:
    settings = Settings(  # type: ignore[call-arg]
        _env_file=None,
        environment=Environment.PRODUCTION,
        secret_key="a-real-secret",
        database_url="postgresql+asyncpg://u:p@db:5432/sb",
    )
    assert not settings.is_sqlite


def test_relative_paths_resolve_against_the_repo_root() -> None:
    from pathlib import Path

    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    resolved = settings.resolve_path(Path("./data/storage"))
    assert resolved.is_absolute()
