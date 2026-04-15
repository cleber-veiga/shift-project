"""
Configuração do Alembic para migrações com SQLAlchemy assíncrono.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import settings
from app.db.base import Base

# Importar o pacote de models para registrar tudo no metadata
from app import models  # noqa: F401

# Configuração de logging do Alembic
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Sobrescrever a URL com a configuração da aplicação
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Metadata alvo para autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Executa migrações em modo 'offline' (gera SQL sem conectar)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Executa migrações com uma conexão ativa."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Executa migrações em modo assíncrono."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Executa migrações em modo 'online' (conecta ao banco)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
