from __future__ import annotations

import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# Make the `app` package importable when alembic is run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.db.base import Base  # noqa: E402
import app.models  # noqa: E402,F401  (registers all ORM models on Base.metadata)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
db_url = settings.DATABASE_URL_SYNC.replace("+psycopg2", "")
db_url = db_url.replace("%", "%%")

config.set_main_option("sqlalchemy.url", db_url)
# Note: migrations run synchronously via psycopg2 driver string above is
# adjusted to plain 'postgresql://' since Alembic's offline/online sync
# runners use a plain sync driver; async runtime traffic still uses
# DATABASE_URL (asyncpg) at app run time.

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Runs migrations using a sync psycopg2 engine for simplicity and
    compatibility with Alembic's transactional DDL handling."""
    from sqlalchemy import create_engine

    sync_url = settings.DATABASE_URL_SYNC
    connectable = create_engine(sync_url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
