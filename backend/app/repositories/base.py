"""Generic repository over SQLAlchemy models.

Services depend on ``AbstractRepository`` (a Protocol), not on SQLAlchemy. That
inversion is what lets us unit-test services against an in-memory fake and, if
we ever need to, move a hot table to a different store without touching callers.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any, Generic, Protocol, TypeVar, cast

from sqlalchemy import CursorResult, Select, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.db.base import Entity

ModelT = TypeVar("ModelT", bound=Entity)


class AbstractRepository(Protocol[ModelT]):
    """The persistence contract services are allowed to know about."""

    async def get(self, entity_id: uuid.UUID) -> ModelT | None: ...
    async def get_or_raise(self, entity_id: uuid.UUID) -> ModelT: ...
    async def list(self, *, limit: int = 50, offset: int = 0) -> Sequence[ModelT]: ...
    async def count(self) -> int: ...
    async def add(self, entity: ModelT) -> ModelT: ...
    async def delete(self, entity_id: uuid.UUID) -> bool: ...


class SQLAlchemyRepository(Generic[ModelT]):
    """Reusable CRUD implementation. Subclasses add query methods, not plumbing.

    Note that no method commits: transaction boundaries belong to the caller
    (the request or the worker job), so several repositories can take part in
    one atomic unit of work.
    """

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    def _base_query(self) -> Select[tuple[ModelT]]:
        """Override to apply default scoping, e.g. soft-delete or tenant filters."""
        return select(self.model)

    async def get(self, entity_id: uuid.UUID) -> ModelT | None:
        result = await self.session.execute(self._base_query().where(self.model.id == entity_id))
        return result.scalar_one_or_none()

    async def get_or_raise(self, entity_id: uuid.UUID) -> ModelT:
        entity = await self.get(entity_id)
        if entity is None:
            raise NotFoundError(
                f"{self.model.__name__} {entity_id} was not found.",
                details={"resource": self.model.__name__, "id": str(entity_id)},
            )
        return entity

    async def find_one_by(self, **filters: Any) -> ModelT | None:
        result = await self.session.execute(self._base_query().filter_by(**filters))
        return result.scalar_one_or_none()

    async def list(self, *, limit: int = 50, offset: int = 0) -> Sequence[ModelT]:
        result = await self.session.execute(self._base_query().limit(limit).offset(offset))
        return result.scalars().all()

    async def count(self) -> int:
        subquery = self._base_query().subquery()
        result = await self.session.execute(select(func.count()).select_from(subquery))
        return int(result.scalar_one())

    async def add(self, entity: ModelT) -> ModelT:
        self.session.add(entity)
        await self.session.flush()  # assign PK/defaults without ending the transaction
        return entity

    async def add_all(self, entities: Sequence[ModelT]) -> Sequence[ModelT]:
        self.session.add_all(list(entities))
        await self.session.flush()
        return entities

    async def delete(self, entity_id: uuid.UUID) -> bool:
        result = cast(
            "CursorResult[Any]",
            await self.session.execute(delete(self.model).where(self.model.id == entity_id)),
        )
        return bool(result.rowcount)
