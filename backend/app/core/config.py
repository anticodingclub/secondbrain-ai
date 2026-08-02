"""Typed application configuration loaded from environment / .env."""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class LogFormat(StrEnum):
    JSON = "json"
    CONSOLE = "console"


class EmbeddingProviderName(StrEnum):
    FASTEMBED = "fastembed"
    SENTENCE_TRANSFORMERS = "sentence_transformers"
    OLLAMA = "ollama"


class LLMProviderName(StrEnum):
    OPENAI = "openai"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"


class StorageBackend(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class Settings(BaseSettings):
    """Single source of truth for runtime configuration.

    Every value is overridable by a ``SECONDBRAIN_``-prefixed environment
    variable, which is what makes the same image run against SQLite locally and
    Postgres + a Qdrant cluster in production.
    """

    model_config = SettingsConfigDict(
        env_prefix="SECONDBRAIN_",
        env_file=(REPO_ROOT / ".env", BACKEND_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Application ──────────────────────────────────────────────────────
    app_name: str = "SecondBrain AI"
    api_v1_prefix: str = "/api/v1"
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "INFO"
    log_format: LogFormat = LogFormat.CONSOLE

    # ── Database ─────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./data/secondbrain.db"
    database_echo: bool = False
    database_pool_size: int = Field(default=10, ge=1, le=100)
    database_max_overflow: int = Field(default=20, ge=0, le=200)

    # ── Vector store ─────────────────────────────────────────────────────
    qdrant_url: str | None = None
    qdrant_api_key: str | None = None
    qdrant_path: Path = Path("./data/qdrant")
    qdrant_collection: str = "secondbrain_chunks"

    # ── Embeddings ───────────────────────────────────────────────────────
    embedding_provider: EmbeddingProviderName = EmbeddingProviderName.FASTEMBED
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dimensions: int = Field(default=384, ge=1)
    embedding_batch_size: int = Field(default=32, ge=1, le=512)

    # ── Storage ──────────────────────────────────────────────────────────
    storage_backend: StorageBackend = StorageBackend.LOCAL
    storage_path: Path = Path("./data/storage")
    max_upload_bytes: int = Field(default=500 * 1024 * 1024, ge=1)

    # ── Security ─────────────────────────────────────────────────────────
    secret_key: str = "change-me-in-production-this-value-is-not-secret"
    access_token_ttl_minutes: int = Field(default=30, ge=1)
    refresh_token_ttl_days: int = Field(default=14, ge=1)

    # ── LLM ──────────────────────────────────────────────────────────────
    llm_provider: LLMProviderName = LLMProviderName.OLLAMA
    llm_model: str = "llama3.1"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None
    gemini_api_key: str | None = None

    # ── HTTP ─────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET"}
        normalized = value.upper()
        if normalized not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}, got {value!r}")
        return normalized

    @model_validator(mode="after")
    def _anchor_sqlite_path(self) -> Settings:
        """Make a relative SQLite path absolute against the repo root.

        Otherwise the app (run from ``backend/``) and Alembic (run from
        anywhere) would silently open two different database files.
        """
        prefix, sep, location = self.database_url.partition(":///")
        if sep and prefix.startswith("sqlite") and location and location != ":memory:":
            candidate = Path(location)
            if not candidate.is_absolute():
                resolved = (REPO_ROOT / candidate).resolve()
                object.__setattr__(self, "database_url", f"{prefix}:///{resolved.as_posix()}")
        return self

    @model_validator(mode="after")
    def _guard_production_defaults(self) -> Settings:
        if self.environment is Environment.PRODUCTION:
            if self.secret_key.startswith("change-me"):
                raise ValueError("SECONDBRAIN_SECRET_KEY must be set in production")
            if self.database_url.startswith("sqlite"):
                raise ValueError("SQLite is not supported in production; use PostgreSQL")
        return self

    @property
    def is_sqlite(self) -> bool:
        return self.database_url.startswith("sqlite")

    @property
    def qdrant_is_embedded(self) -> bool:
        """True when Qdrant runs in-process against a local path instead of a server."""
        return not self.qdrant_url

    def resolve_path(self, path: Path) -> Path:
        """Resolve a possibly-relative configured path against the repo root."""
        return path if path.is_absolute() else (REPO_ROOT / path).resolve()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings accessor — the composition root for configuration."""
    return Settings()
