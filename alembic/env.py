"""
Alembic env.py — async SQLAlchemy (asyncpg) compatible
=======================================================
This file is loaded by Alembic for every migration command.
It reads the DB URL from config.py so it always matches the running app.

How to use:
  # After changing any model in models/:
  python -m alembic revision --autogenerate -m "add foo_column to bar_table"

  # Apply all pending migrations to the live DB:
  python -m alembic upgrade head

  # See what revision the DB is on:
  python -m alembic current
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# ── Make sure the project root is on sys.path ─────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ── Import ORM Base + all models (so metadata is fully populated) ─────────────
from database import Base          # noqa: E402
from config   import DATABASE_URL  # noqa: E402
import models                      # noqa: E402, F401  ← registers all tables

# ── Alembic config object ─────────────────────────────────────────────────────
config = context.config

# Override sqlalchemy.url with the value from config.py
config.set_main_option("sqlalchemy.url", DATABASE_URL)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The metadata Alembic compares against the live DB
target_metadata = Base.metadata


# ── Offline mode (generate SQL without connecting) ────────────────────────────

def run_migrations_offline() -> None:
    """Generate migration SQL to stdout without a live DB connection."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


# ── Online mode (run against live DB) ────────────────────────────────────────

def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Connect via asyncpg and run migrations inside run_sync."""
    connectable = create_async_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


# ── Entry point ───────────────────────────────────────────────────────────────

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
