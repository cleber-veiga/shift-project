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
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.connection import Connection
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionDiagnosePayload,
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

# Caminho da libfbclient 2.5 dentro do container — definido pelo Dockerfile.
# Usado quando extra_params.firebird_version == "2.5".
_FB25_LIB_PATH = "/opt/firebird-2.5/lib/libfbclient.so.2"


def _firebird_version(conn: "Connection") -> str:
    """Le firebird_version de extra_params. "2.5", "3+" ou "auto" (default "3+").

    "auto" significa que o backend devera detectar a versao a partir do
    ODS do arquivo .fdb no momento da conexao (via firebird_client.py).
    """
    raw = ""
    if conn.extra_params:
        raw = str(conn.extra_params.get("firebird_version") or "").strip().lower()
    if raw in {"2.5", "2", "fb2", "fb2.5", "fdb"}:
        return "2.5"
    if raw in {"auto", "autodetect", "detectar"}:
        return "auto"
    return "3+"


def _resolve_firebird_version_for_conn(conn: "Connection") -> str:
    """Resolve "auto" lendo ODS do arquivo. Devolve sempre "2.5" ou "3+".

    Necessario na build_connection_string porque la nao da pra adiar a
    decisao para o connect (precisamos saber qual dialect SA usar). Se a
    deteccao falhar, default seguro = "3+".
    """
    version = _firebird_version(conn)
    if version != "auto":
        return version

    from app.services.firebird_client import (
        _is_bundled_host,
        resolve_firebird_version_from_path,
        translate_host_path_to_container,
    )

    # Auto-deteccao via filesystem so e possivel quando o arquivo .fdb esta
    # acessivel via mount /firebird/data — caso dos servidores bundled. Para
    # servidor remoto nao temos acesso ao arquivo; default seguro = "3+".
    if not _is_bundled_host(conn.host):
        return "3+"

    container_path = translate_host_path_to_container(conn.database, conn.host)
    detected = resolve_firebird_version_from_path(container_path)
    return detected or "3+"

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

        # exclude_unset=True (nao exclude_none): respeita null explicito como
        # "limpa este campo" — necessario pra UI conseguir remover extra_params
        # ao trocar firebird_version 2.5 -> 3+, ou limpar include_schemas, etc.
        # Campos que o frontend nao mandou no JSON simplesmente nao aparecem
        # no dump e ficam intactos.
        updates = data.model_dump(exclude_unset=True)

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

    async def diagnose_payload(
        self,
        payload: ConnectionDiagnosePayload,
    ) -> dict[str, Any]:
        """Diagnostico stateless — testa um payload sem persistir.

        Para Firebird: roda o pipeline em 4 etapas via diagnose().
        Para outros tipos: monta a connection string em memoria e roda
        _test_sync, devolvendo 1 step ('test') compativel com o mesmo
        formato do pipeline Firebird.
        """
        from app.services.firebird_diagnostics import (
            diagnose,
            first_failure,
            overall_ok,
        )

        if payload.type == ConnectionType.firebird:
            extra = dict(payload.extra_params) if payload.extra_params else {}
            steps = await asyncio.wait_for(
                asyncio.to_thread(
                    diagnose,
                    host=payload.host,
                    port=int(payload.port),
                    database=payload.database,
                    username=payload.username,
                    password=payload.password,
                    firebird_version=str(extra.get("firebird_version") or "3+"),
                    charset=str(extra.get("charset") or "WIN1252"),
                    role=extra.get("role") or None,
                ),
                timeout=settings.CONNECTION_TEST_TIMEOUT_SECONDS,
            )
            failure = first_failure(steps)
            return {
                "overall_ok": overall_ok(steps),
                "first_failure_stage": failure["stage"] if failure else None,
                "steps": steps,
            }

        # Demais tipos: 1 step "test" via SQLAlchemy. Reutiliza
        # build_connection_string instanciando um Connection efemero (em
        # memoria, nao adicionado a sessao) — mesmo path de URL building
        # usado por conexoes persistidas.
        ephemeral = Connection(
            workspace_id=None,
            project_id=None,
            player_id=None,
            name="__diagnose_payload__",
            type=payload.type.value,
            host=payload.host,
            port=int(payload.port),
            database=payload.database,
            username=payload.username,
            password=payload.password,
            extra_params=payload.extra_params,
            include_schemas=None,
            is_public=False,
            created_by_id=None,
        )
        url = self.build_connection_string(ephemeral)

        import time
        t0 = time.monotonic()
        try:
            success, message = await asyncio.wait_for(
                asyncio.to_thread(self._test_sync, url, payload.type.value),
                timeout=settings.CONNECTION_TEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            success = False
            message = (
                f"Timeout ao conectar ({int(settings.CONNECTION_TEST_TIMEOUT_SECONDS)}s)."
            )
        latency_ms = int((time.monotonic() - t0) * 1000)

        step = {
            "stage": "test",
            "ok": success,
            "latency_ms": latency_ms,
            "error_class": None if success else "unknown",
            "error_msg": None if success else message,
            "hint": None if success else message,
        }
        return {
            "overall_ok": success,
            "first_failure_stage": None if success else "test",
            "steps": [step],
        }

    async def diagnose_connection(
        self,
        db: AsyncSession,
        connection_id: UUID,
    ) -> dict[str, Any]:
        """Roda o pipeline de diagnostico Firebird (4 etapas).

        Devolve dict no formato {overall_ok, first_failure_stage, steps}.
        Para conexoes nao-Firebird, retorna estrutura vazia com mensagem.
        """
        from app.services.firebird_diagnostics import (
            diagnose,
            first_failure,
            overall_ok,
        )

        conn = await self.get(db, connection_id)
        if conn is None:
            raise LookupError("Conexao nao encontrada.")
        if conn.type != ConnectionType.firebird.value:
            raise ValueError(
                "Diagnostico estruturado esta disponivel apenas para conexoes Firebird."
            )

        extra = dict(conn.extra_params) if conn.extra_params else {}

        steps = await asyncio.wait_for(
            asyncio.to_thread(
                diagnose,
                host=conn.host or "",
                port=int(conn.port or 0),
                database=conn.database or "",
                username=conn.username or "",
                password=conn.password or "",
                firebird_version=str(extra.get("firebird_version") or "3+"),
                charset=str(extra.get("charset") or "WIN1252"),
                role=extra.get("role") or None,
            ),
            timeout=settings.CONNECTION_TEST_TIMEOUT_SECONDS,
        )
        failure = first_failure(steps)
        return {
            "overall_ok": overall_ok(steps),
            "first_failure_stage": failure["stage"] if failure else None,
            "steps": steps,
        }

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
                timeout=settings.CONNECTION_TEST_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return TestConnectionResult(
                success=False,
                message=f"Timeout ao conectar ({int(settings.CONNECTION_TEST_TIMEOUT_SECONDS)}s).",
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
        """Testa Firebird rodando o pipeline de diagnostico (DNS->TCP->
        greeting->auth_query). Em caso de falha, devolve o hint PT-BR
        acionavel da etapa que quebrou — em vez do str(exc) cru."""
        from app.services.firebird_diagnostics import (
            diagnose,
            first_failure,
            overall_ok,
        )

        extra = dict(conn.extra_params) if conn.extra_params else {}
        steps = diagnose(
            host=conn.host or "",
            port=int(conn.port or 0),
            database=conn.database or "",
            username=conn.username or "",
            password=conn.password or "",
            firebird_version=str(extra.get("firebird_version") or "3+"),
            charset=str(extra.get("charset") or "WIN1252"),
            role=extra.get("role") or None,
        )
        if overall_ok(steps):
            return True, "Conexao bem-sucedida."
        failure = first_failure(steps)
        return False, (failure["hint"] if failure and failure["hint"] else "Falha desconhecida.")

    def build_connection_string(self, conn: Connection) -> str:
        driver = _SA_DRIVERS.get(conn.type, conn.type)
        # EncryptedString retorna None quando a descriptografia falha (ex: a
        # ENCRYPTION_KEY do .env mudou desde que a senha foi salva). Antes
        # quebrava em quote_plus(None) com 'expected bytes' — mensagem inutil.
        if conn.password is None:
            raise ValueError(
                f"Senha da conexao '{conn.name}' nao pode ser descriptografada. "
                "Verifique se ENCRYPTION_KEY no .env nao mudou desde que a "
                "conexao foi salva — se mudou, edite a conexao e reinforme a senha."
            )
        password_encoded = quote_plus(conn.password)

        # Firebird: o campo 'database' e um caminho do sistema de arquivos que
        # pode conter ':' e '\' (Windows). quote_plus quebra porque SA nao
        # decodifica url.database de volta — driver recebe a string encoded e
        # tenta abrir um arquivo literalmente chamado 'D%3A%5C...'. URL.create
        # trata o database como campo bruto e o render_as_string + make_url
        # round-trip preserva o path.
        #
        # Versao do servidor decide qual dialect/driver usar:
        #   - "3+" -> firebird+firebird (firebird-driver, suporta FB 3.0+)
        #   - "2.5" -> firebird+fdb     (fdb legado, suporta FB 2.5)
        # Para fdb, fb_library_name aponta para a libfbclient 2.5 instalada
        # no container — sem isso, fdb cai no libfbclient do sistema (4.0)
        # que rejeita ODS 11.2 com "unsupported on-disk structure".
        if conn.type == ConnectionType.firebird.value:
            from app.services.firebird_client import translate_host_path_to_container
            # Resolve "auto" lendo o ODS do arquivo (se acessivel via mount).
            fb_version = _resolve_firebird_version_for_conn(conn)
            fb_driver_name = "firebird+fdb" if fb_version == "2.5" else "firebird+firebird"
            # Traducao do path: usuario informa 'D:\Data\X.FDB' (como ele ve
            # no Windows). Convertemos para o caminho dentro do container
            # (/firebird/data/Data/X.FDB) que e onde os servidores bundled
            # firebird25/firebird30 acham o arquivo. Para host remoto a
            # funcao preserva o path original.
            db_translated = translate_host_path_to_container(conn.database, conn.host)
            base = URL.create(
                drivername=fb_driver_name,
                username=conn.username,
                password=conn.password,
                host=conn.host,
                port=conn.port,
                database=db_translated,
            ).render_as_string(hide_password=False)
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

        # firebird_version e config interna do app (define qual driver usar) —
        # nao deve vazar pra URL final, o dialect nao reconhece.
        extra_params.pop("firebird_version", None)

        # SQL Server via pyodbc exige que o driver ODBC seja especificado.
        # Injeta um padrão se o usuário não tiver configurado nenhum.
        if conn.type == ConnectionType.sqlserver.value and "driver" not in extra_params:
            extra_params["driver"] = "ODBC Driver 17 for SQL Server"

        # Firebird 2.5 (dialect +fdb): injeta fb_library_name apontando para a
        # libfbclient 2.5 do container, se nao foi configurado. fdb passa esse
        # kwarg direto pra fdb.connect(), que carrega a lib indicada em vez de
        # cair no libfbclient do sistema (que e FB 4.0 e rejeita ODS 2.5).
        if (
            conn.type == ConnectionType.firebird.value
            and _firebird_version(conn) == "2.5"
            and "fb_library_name" not in extra_params
        ):
            extra_params["fb_library_name"] = _FB25_LIB_PATH

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
