"""
Servico de conectores de banco de dados.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import quote_plus
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.connection import Connection
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionType,
    ConnectionUpdate,
    TestConnectionResult,
)
from app.services.db.engine_cache import invalidate_engine

_SA_DRIVERS: dict[str, str] = {
    ConnectionType.oracle.value: "oracle+oracledb",
    ConnectionType.postgresql.value: "postgresql+psycopg2",
    ConnectionType.firebird.value: "firebird+firebird",
    ConnectionType.sqlserver.value: "mssql+pyodbc",
    ConnectionType.mysql.value: "mysql+pymysql",
}

_TEST_TIMEOUT_SECONDS: float = 5.0
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


class ConnectionService:
    """CRUD + teste de conectividade + resolucao de connection_id em connection_string."""

    async def create(
        self,
        db: AsyncSession,
        data: ConnectionCreate,
        created_by_id: UUID,
    ) -> Connection:
        conn = Connection(
            workspace_id=data.workspace_id,
            project_id=data.project_id,
            player_id=data.player_id,
            name=data.name,
            type=data.type.value,
            host=data.host,
            port=data.port,
            database=data.database,
            username=data.username,
            password=data.password,
            extra_params=data.extra_params,
            include_schemas=data.include_schemas,
            is_public=data.is_public,
            created_by_id=created_by_id,
        )
        db.add(conn)
        await db.flush()
        await db.refresh(conn)
        return conn

    async def list(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        current_user_id: UUID,
    ) -> list[Connection]:
        """Retorna conexoes do workspace visiveis ao usuario:
        publicas (is_public=True) ou criadas pelo proprio usuario."""
        result = await db.execute(
            select(Connection)
            .where(
                Connection.workspace_id == workspace_id,
                or_(
                    Connection.is_public.is_(True),
                    Connection.created_by_id == current_user_id,
                ),
            )
            .order_by(Connection.name)
        )
        return list(result.scalars().all())

    async def list_paginated(
        self,
        db: AsyncSession,
        workspace_id: UUID,
        current_user_id: UUID,
        *,
        page: int,
        size: int,
    ) -> tuple[list[Connection], int]:
        """Versao paginada de :meth:`list`: retorna (items, total)."""
        filters = [
            Connection.workspace_id == workspace_id,
            or_(
                Connection.is_public.is_(True),
                Connection.created_by_id == current_user_id,
            ),
        ]
        total = await db.scalar(
            select(func.count()).select_from(Connection).where(*filters)
        )
        stmt = (
            select(Connection)
            .where(*filters)
            .order_by(Connection.name, Connection.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), int(total or 0)

    async def list_for_project(
        self,
        db: AsyncSession,
        project_id: UUID,
        workspace_id: UUID,
        current_user_id: UUID,
    ) -> list[Connection]:
        """Retorna conexoes do projeto e do workspace pai visiveis ao usuario:
        publicas (is_public=True) ou criadas pelo proprio usuario."""
        result = await db.execute(
            select(Connection)
            .where(
                or_(
                    Connection.workspace_id == workspace_id,
                    Connection.project_id == project_id,
                ),
                or_(
                    Connection.is_public.is_(True),
                    Connection.created_by_id == current_user_id,
                ),
            )
            .order_by(Connection.name)
        )
        return list(result.scalars().all())

    async def list_for_project_paginated(
        self,
        db: AsyncSession,
        project_id: UUID,
        workspace_id: UUID,
        current_user_id: UUID,
        *,
        page: int,
        size: int,
    ) -> tuple[list[Connection], int]:
        """Versao paginada de :meth:`list_for_project`: retorna (items, total)."""
        filters = [
            or_(
                Connection.workspace_id == workspace_id,
                Connection.project_id == project_id,
            ),
            or_(
                Connection.is_public.is_(True),
                Connection.created_by_id == current_user_id,
            ),
        ]
        total = await db.scalar(
            select(func.count()).select_from(Connection).where(*filters)
        )
        stmt = (
            select(Connection)
            .where(*filters)
            .order_by(Connection.name, Connection.id)
            .offset((page - 1) * size)
            .limit(size)
        )
        result = await db.execute(stmt)
        return list(result.scalars().all()), int(total or 0)

    async def get(
        self,
        db: AsyncSession,
        connection_id: UUID,
    ) -> Connection | None:
        result = await db.execute(
            select(Connection).where(Connection.id == connection_id)
        )
        return result.scalar_one_or_none()

    async def update(
        self,
        db: AsyncSession,
        connection_id: UUID,
        data: ConnectionUpdate,
    ) -> Connection | None:
        conn = await self.get(db, connection_id)
        if conn is None:
            return None

        # Captura a identidade ANTERIOR antes do mutate. Se host/port/db/user
        # mudou, precisamos invalidar a chave antiga; se nao, a chave nova
        # pode coincidir e a invalidacao garante que credenciais novas
        # entrem em vigor na proxima get_engine().
        previous_key = self._engine_cache_key_for(conn)

        updates = data.model_dump(exclude_none=True)

        for field, value in updates.items():
            setattr(conn, field, value)

        await db.flush()
        await db.refresh(conn)

        # Invalida a entrada anterior e a atual (caso a chave nao tenha
        # mudado, a chamada e idempotente — o segundo invalidate retorna
        # False sem efeito).
        self._invalidate_cached_engine(previous_key)
        self._invalidate_cached_engine(self._engine_cache_key_for(conn))
        return conn

    async def delete(
        self,
        db: AsyncSession,
        connection_id: UUID,
    ) -> bool:
        conn = await self.get(db, connection_id)
        if conn is None:
            return False
        cache_key = self._engine_cache_key_for(conn)
        await db.delete(conn)
        await db.flush()
        self._invalidate_cached_engine(cache_key)
        return True

    @staticmethod
    def _engine_cache_key_for(conn: Connection) -> dict[str, Any]:
        """Extrai os campos que compoem a chave do engine_cache."""
        return {
            "workspace_id": conn.workspace_id,
            "conn_type": conn.type,
            "host": conn.host or "",
            "port": int(conn.port or 0),
            "database": conn.database or "",
            "username": conn.username or "",
        }

    @staticmethod
    def _invalidate_cached_engine(key: dict[str, Any]) -> None:
        try:
            invalidate_engine(
                key["workspace_id"],
                conn_type=key["conn_type"],
                host=key["host"],
                port=key["port"],
                database=key["database"],
                username=key["username"],
            )
        except Exception:  # noqa: BLE001 — invalidacao nao pode bloquear o CRUD
            pass

    async def test_connection(
        self,
        db: AsyncSession,
        connection_id: UUID,
    ) -> TestConnectionResult:
        conn = await self.get(db, connection_id)
        if conn is None:
            return TestConnectionResult(success=False, message="Conexao nao encontrada.")

        # Firebird: usa driver direto para evitar parsing de URL (caminhos Windows)
        if conn.type == ConnectionType.firebird.value:
            worker = self._test_firebird_sync
            target = conn
        else:
            worker = self._test_sync  # type: ignore[assignment]
            target = self.build_connection_string(conn)  # type: ignore[assignment]

        try:
            extra = {"conn_type": conn.type} if worker is self._test_sync else {}
            success, message = await asyncio.wait_for(
                asyncio.to_thread(worker, target, **extra),
                timeout=_TEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return TestConnectionResult(
                success=False,
                message=f"Timeout ao conectar ({int(_TEST_TIMEOUT_SECONDS)}s).",
            )

        return TestConnectionResult(success=success, message=message)

    @staticmethod
    def _test_sync(url: str, conn_type: str = "") -> tuple[bool, str]:
        _PING_QUERY: dict[str, str] = {
            ConnectionType.oracle.value: "SELECT 1 FROM DUAL",
        }
        ping = _PING_QUERY.get(conn_type, "SELECT 1")
        engine: sa.Engine | None = None
        try:
            engine = sa.create_engine(url, pool_pre_ping=False, pool_size=1, max_overflow=0)
            with engine.connect() as db_conn:
                db_conn.execute(sa.text(ping))
            return True, "Conexao bem-sucedida."
        except Exception as exc:
            return False, str(exc)
        finally:
            if engine is not None:
                engine.dispose()

    @staticmethod
    def _test_firebird_sync(conn: "Connection") -> tuple[bool, str]:
        """Testa Firebird via driver direto — sem SQLAlchemy URL parsing."""
        from app.services.firebird_client import connect_firebird

        config: dict[str, Any] = {
            "host": conn.host,
            "port": conn.port,
            "database": conn.database,
            "username": conn.username,
        }
        # extra_params pode conter: role, charset, client_library_path, dsn, connection_url
        if conn.extra_params:
            config.update(conn.extra_params)

        secret = {"password": conn.password}

        fb_conn = None
        try:
            fb_conn = connect_firebird(config=config, secret=secret)
            cur = fb_conn.cursor()
            cur.execute("select 1 from rdb$database")
            cur.fetchone()
            cur.close()
            return True, "Conexao bem-sucedida."
        except Exception as exc:
            return False, str(exc)
        finally:
            if fb_conn is not None:
                try:
                    fb_conn.close()
                except Exception:
                    pass

    def build_connection_string(self, conn: Connection) -> str:
        driver = _SA_DRIVERS.get(conn.type, conn.type)
        password_encoded = quote_plus(conn.password)

        # Firebird: o campo 'database' é um caminho do sistema de arquivos que pode
        # conter barras invertidas e letras de drive (Windows).  Usamos o formato
        # clássico host/port:path, codificando apenas o password.
        if conn.type == ConnectionType.firebird.value:
            db_encoded = quote_plus(conn.database)
            base = (
                f"{driver}://{conn.username}:{password_encoded}"
                f"@{conn.host}:{conn.port}/{db_encoded}"
            )
        elif conn.type == ConnectionType.oracle.value:
            # SQLAlchemy+oracledb interpreta "host:port/name" como SID.
            # Para SERVICE_NAME (padrão moderno), o campo database vai como
            # query-param: "host:port/?service_name=name".
            svc = quote_plus(conn.database)
            base = (
                f"{driver}://{conn.username}:{password_encoded}"
                f"@{conn.host}:{conn.port}/?service_name={svc}"
            )
        else:
            base = (
                f"{driver}://{conn.username}:{password_encoded}"
                f"@{conn.host}:{conn.port}/{conn.database}"
            )

        extra_params = dict(conn.extra_params) if conn.extra_params else {}

        # SQL Server via pyodbc exige que o driver ODBC seja especificado.
        # Injeta um padrão se o usuário não tiver configurado nenhum.
        if conn.type == ConnectionType.sqlserver.value and "driver" not in extra_params:
            extra_params["driver"] = "ODBC Driver 17 for SQL Server"

        if extra_params:
            sep = "&" if "?" in base else "?"
            qs = "&".join(
                f"{quote_plus(str(k))}={quote_plus(str(v))}"
                for k, v in extra_params.items()
            )
            base = f"{base}{sep}{qs}"
        return base

    async def get_connection_string_by_id(
        self,
        db: AsyncSession,
        connection_id: UUID,
        project_id: UUID | None,
        workspace_id: UUID | None,
    ) -> str | None:
        scope_filters = []
        if workspace_id is not None:
            scope_filters.append(Connection.workspace_id == workspace_id)
        if project_id is not None:
            scope_filters.append(Connection.project_id == project_id)

        if not scope_filters:
            return None

        result = await db.execute(
            select(Connection).where(
                Connection.id == connection_id,
                or_(*scope_filters),
            )
        )
        conn = result.scalar_one_or_none()
        if conn is None:
            return None
        return self.build_connection_string(conn)

    async def resolve_for_workflow(
        self,
        db: AsyncSession,
        definition: dict[str, Any],
        project_id: UUID | None,
        workspace_id: UUID | None,
    ) -> dict[str, str]:
        """Resolve todas as connection_ids do workflow em 1 query batch com IN clause."""
        connection_id_strs = _collect_connection_ids(definition)
        if not connection_id_strs:
            return {}

        connection_uuids = [UUID(cid) for cid in connection_id_strs]

        scope_filters = []
        if workspace_id is not None:
            scope_filters.append(Connection.workspace_id == workspace_id)
        if project_id is not None:
            scope_filters.append(Connection.project_id == project_id)

        if not scope_filters:
            raise ValueError("Nenhum escopo (workspace ou project) informado para resolver conexoes.")

        result = await db.execute(
            select(Connection).where(
                Connection.id.in_(connection_uuids),
                or_(*scope_filters),
            )
        )
        connections = {str(conn.id): conn for conn in result.scalars().all()}

        resolved: dict[str, str] = {}
        for conn_id_str in connection_id_strs:
            conn = connections.get(conn_id_str)
            if conn is None:
                raise ValueError(
                    f"Conexao '{conn_id_str}' nao encontrada no escopo autorizado. "
                    "Verifique se o conector existe e pertence ao projeto ou workspace."
                )
            resolved[conn_id_str] = self.build_connection_string(conn)

        return resolved


def _collect_connection_ids(obj: Any, _found: set[str] | None = None) -> set[str]:
    if _found is None:
        _found = set()

    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == "connection_id" and isinstance(value, str) and _UUID_RE.match(value):
                _found.add(value)
            else:
                _collect_connection_ids(value, _found)
    elif isinstance(obj, list):
        for item in obj:
            _collect_connection_ids(item, _found)

    return _found


connection_service = ConnectionService()
