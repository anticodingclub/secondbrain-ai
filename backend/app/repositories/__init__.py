"""Repository layer — the only place that talks SQL."""

from app.repositories.base import AbstractRepository, SQLAlchemyRepository

__all__ = ["AbstractRepository", "SQLAlchemyRepository"]
