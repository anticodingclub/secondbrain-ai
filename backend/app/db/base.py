"""Declarative base and column conventions shared by every model."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, ClassVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON, Uuid

# Explicit naming so Alembic emits stable, human-readable constraint names and
# can autogenerate DROP statements for them across both backends.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

#: JSONB on Postgres (indexable, binary) and plain JSON on SQLite.
JSONType = JSON().with_variant(postgresql.JSONB(), "postgresql")

#: Native UUID on Postgres, CHAR(32) elsewhere — one Python type, two storages.
UUIDType = Uuid(as_uuid=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict: JSONType, uuid.UUID: UUIDType}


class UUIDPrimaryKeyMixin:
    """UUID primary keys so ids can be generated client-side and stay
    non-enumerable across tenants."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUIDType, primary_key=True, default=uuid.uuid4, sort_order=-100
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), default=utcnow, sort_order=100
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        default=utcnow,
        onupdate=utcnow,
        sort_order=101,
    )


class Entity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Base for every persisted entity.

    Giving the generic repository a bound that actually declares ``id`` is what
    lets ``SQLAlchemyRepository[T]`` be type-checked rather than trusted.
    """

    __abstract__ = True
