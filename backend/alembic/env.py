"""Alembic environment — async engine, settings-driven URL."""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from alembic.autogenerate.api import AutogenContext as AutoGenContext
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy.types import TypeEngine

from app.core.config import get_settings
from app.db.base import Base, JSONType, UTCDateTime
from app.db.session import ensure_sqlite_directory
from app.models import *  # noqa: F401,F403  (registers every table on Base.metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
ensure_sqlite_directory(settings)
# Escape '%' so ConfigParser interpolation does not mangle URL-encoded passwords.
config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))

target_metadata = Base.metadata


def _render_item(type_: str, obj: object, autogen_context: AutoGenContext) -> str | bool:
    """Render our custom types as plain SQLAlchemy types.

    Two problems autogenerate creates on its own:

    ``JSONType`` is emitted as ``postgresql.JSONB(astext_type=Text())`` with
    ``Text`` unqualified, which does not import and fails at runtime.

    ``UTCDateTime`` is emitted as ``app.db.base.UTCDateTime(...)``, which fails
    the same way — and should not appear at all. A migration describes a
    *schema*, not the Python types that happened to produce it. Referencing
    application code binds an immutable migration to a layer that will be
    refactored, so a rename years from now would break history that already
    ran everywhere.
    """
    if type_ != "type" or not isinstance(obj, TypeEngine):
        return False

    if obj is JSONType:
        autogen_context.imports.add("from sqlalchemy.dialects import postgresql")
        return "sa.JSON().with_variant(postgresql.JSONB(), 'postgresql')"

    if isinstance(obj, UTCDateTime):
        return "sa.DateTime(timezone=True)"

    return False


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        render_item=_render_item,
        # SQLite cannot ALTER most columns; batch mode rebuilds the table instead
        # so the same migration script runs on both backends.
        render_as_batch=settings.is_sqlite,
    )


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=settings.is_sqlite,
    )
    with context.begin_transaction():
        context.run_migrations()


def _do_run_migrations(connection: Connection) -> None:
    _configure(connection)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    engine = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with engine.connect() as connection:
        await connection.run_sync(_do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
