"""
Configuração do engine assíncrono e fábrica de sessões do SQLAlchemy.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

# Engine assíncrono — pool dimensionado para limites de conexão do Neon/cloud
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

# Fábrica de sessões — expire_on_commit=False evita lazy-load em contexto async
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_async_session() -> AsyncGenerator[AsyncSession, None]:
    """Generator de sessão para injeção de dependência do FastAPI."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# Alias reexportado como dependência FastAPI. FastAPI cacheia dependências por
# identidade de callable dentro de uma request; manter UM único símbolo
# (`get_db`) usado em toda a cadeia de Depends garante que apenas uma sessão
# seja aberta por request, em vez de uma por lugar que chamava "get_db" local.
get_db = get_async_session
