"""
Cliente Firebird direto — evita o parsing de URL do SQLAlchemy,
que quebra caminhos Windows (barras invertidas, letra de drive).

Tenta firebird-driver primeiro; cai para fdb como fallback.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _build_database_dsn(config: dict[str, Any]) -> str:
    """
    Monta o valor de ``database`` aceito pelo firebird-driver / fdb.

    Prioridade:
      1. ``connection_url``  — repassado literalmente
      2. ``dsn``             — repassado literalmente
      3. ``host/port:database``  — montado a partir dos campos individuais
    """
    connection_url = config.get("connection_url")
    if connection_url:
        return str(connection_url)

    dsn = config.get("dsn")
    if dsn:
        return str(dsn)

    host = config.get("host")
    port = int(config.get("port") or 3050)
    database = config.get("database")

    if not host or not database:
        raise ValueError(
            "host e database são obrigatórios para Firebird quando dsn/connection_url não são usados."
        )

    return f"{host}/{port}:{database}"


def _resolve_client_library(config: dict[str, Any]) -> str | None:
    """Tenta localizar o fbclient.dll — retorna None se não encontrar."""
    configured = config.get("client_library_path")
    if configured:
        path = Path(str(configured))
        if path.exists():
            return str(path)

    candidates = [
        r"C:\Program Files\Firebird\Firebird_5_0\fbclient.dll",
        r"C:\Program Files\Firebird\Firebird_4_0\fbclient.dll",
        r"C:\Program Files\Firebird\Firebird_3_0\fbclient.dll",
        r"C:\Program Files\Firebird\Firebird_2_5\bin\fbclient.dll",
        "/usr/lib/x86_64-linux-gnu/libfbclient.so.2",
        "/usr/lib/libfbclient.so",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def connect_firebird(
    config: dict[str, Any],
    secret: dict[str, Any] | None,
) -> Any:
    """
    Retorna uma conexão DBAPI ao banco Firebird.

    Parâmetros lidos de ``config``:
      - host, port, database     — obrigatórios (ou dsn / connection_url)
      - username                 — usuário do banco
      - role                     — role opcional
      - charset                  — charset (padrão: UTF8)
      - client_library_path      — caminho explícito para fbclient.dll/.so
      - dsn                      — DSN completo (substitui host/port/database)
      - connection_url           — URL literal passada diretamente ao driver

    ``secret`` deve conter ``password``.
    """
    user = config.get("username")
    password = (secret or {}).get("password")
    role = config.get("role") or None
    charset = config.get("charset") or "WIN1252"
    database_dsn = _build_database_dsn(config)
    client_library = _resolve_client_library(config)

    # ── Tentativa 1: firebird-driver (driver oficial Python 3) ────────────────
    driver_exc: Exception | None = None
    try:
        from firebird import driver as fb_driver  # type: ignore[import-untyped]

        if client_library:
            fb_driver.driver_config.fb_client_library.value = client_library  # type: ignore[attr-defined]

        kwargs: dict[str, Any] = {
            "database": database_dsn,
            "user": user,
            "password": password,
            "charset": charset,
        }
        if role:
            kwargs["role"] = role

        return fb_driver.connect(**kwargs)
    except Exception as exc:
        driver_exc = exc

    # ── Tentativa 2: fdb (legado, mas amplamente instalado) ───────────────────
    try:
        import fdb  # type: ignore[import-untyped]

        fdb_kwargs: dict[str, Any] = {
            "dsn": database_dsn,
            "user": user,
            "password": password,
            "charset": charset,
        }
        if role:
            fdb_kwargs["role"] = role
        if client_library:
            fdb_kwargs["fb_library_name"] = client_library

        return fdb.connect(**fdb_kwargs)
    except Exception as fdb_exc:
        if driver_exc is not None:
            raise RuntimeError(
                f"Falha com firebird-driver: {driver_exc}; "
                f"Falha com fdb: {fdb_exc}"
            ) from fdb_exc
        raise
