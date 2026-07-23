"""Alembic environment. Resolves the database URL at runtime (config override ->
MINILP_DATABASE_URL env -> application settings) and targets the ORM metadata so
``--autogenerate`` and ``upgrade`` stay in sync with the models."""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Import models so their tables register on Base.metadata.
import app.models  # noqa: F401,E402
from app.config import settings
from app.db import Base

config = context.config
_url = (
    config.get_main_option("sqlalchemy.url")
    or os.environ.get("MINILP_DATABASE_URL")
    or settings.database_url
)
config.set_main_option("sqlalchemy.url", _url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
