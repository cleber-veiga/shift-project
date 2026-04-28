"""
Cliente Firebird direto — evita o parsing de URL do SQLAlchemy,
que quebra caminhos Windows (barras invertidas, letra de drive).

Suporta servidores Firebird 2.5 e 3.0+ via dois drivers distintos:
  - firebird-driver (moderno) -> servidores FB 3.0+ via libfbclient 4.0
  - fdb (legado)              -> servidores FB 2.5 via libfbclient 2.5

A versao e selecionada por ``config["firebird_version"]`` ("2.5", "3+" ou
"auto"). Quando "auto", o detector le o ODS do header do arquivo .fdb e
escolhe o driver/servidor automaticamente — desde que o arquivo seja
acessivel via bind-mount em /firebird/data.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Caminho fixo onde o Dockerfile coloca a libfbclient 2.5 com RPATH ja seteado
# para suas deps ICU 3.0 bundled. Em hosts Windows/dev local, _resolve_fb25_lib
# tambem procura instalacoes locais comuns.
_FB25_LIB_LINUX = "/opt/firebird-2.5/lib/libfbclient.so.2"

# Diretorio onde os .fdb dos clientes ficam montados no container. Usado
# tanto pelos servidores firebird25/firebird30 (read-write) quanto pelo
# shift-backend (read-only) para deteccao de ODS.
_LOCAL_FDB_MOUNT = "/firebird/data"

# Hosts cujo filesystem e o mesmo que o backend ve em /firebird/data — so
# nesses casos faz sentido reescrever o path. Para qualquer outro host
# (servidor remoto no Windows do cliente, IP externo, FQDN, ou ate
# 'localhost' que aponta pra maquina do cliente, nao pro container)
# o arquivo NAO esta no nosso mount — preserva o path.
_BUNDLED_HOSTS = frozenset({"firebird25", "firebird30"})


def _is_bundled_host(host: str | None) -> bool:
    """True se o host alvo e um servidor Firebird bundled (mesmo mount)."""
    if not host:
        # host vazio/None significa auto-detect via mount local — sem
        # servidor remoto, traducao se aplica.
        return True
    h = host.strip().lower()
    if h in _BUNDLED_HOSTS:
        return True
    # Caso o compose adicione dominio (ex: firebird25.shift-net).
    return h.startswith(("firebird25.", "firebird30."))


def detect_fdb_ods(file_path: str) -> tuple[int, int] | None:
    """Le o header de um .fdb e devolve (ods_major, ods_minor).

    Funciona offline — abre o arquivo direto e le os bytes do header,
    SEM precisar de servidor Firebird. Util para auto-rotear para o
    server certo (FB 2.5 server para ODS 11, FB 3 para ODS 12, etc).

    Layout do header page (page 0) do Firebird (offsets little-endian):
        0-15:  pag_* (page header)
        16-17: hdr_page_size       (USHORT)
        18-19: hdr_ods_version     (USHORT) <- ODS major
        ...
        39:    hdr_ods_minor       (UCHAR)  <- ODS minor

    Retorna None se o arquivo nao puder ser lido ou nao parecer .fdb.
    """
    try:
        with open(file_path, "rb") as f:
            header = f.read(64)
    except (OSError, FileNotFoundError):
        return None

    if len(header) < 64:
        return None

    try:
        ods_major = int.from_bytes(header[18:20], "little")
        ods_minor = header[39]
    except (IndexError, ValueError):
        return None

    # Sanity check — Firebird ODS validos sao 10..14.
    if ods_major < 10 or ods_major > 14:
        return None

    return (ods_major, ods_minor)


def resolve_firebird_version_from_path(file_path: str) -> str | None:
    """Le ODS do arquivo e devolve "2.5" ou "3+" para uso em config.

    None se nao conseguir ler (arquivo inacessivel, nao e .fdb, etc).
    """
    ods = detect_fdb_ods(file_path)
    if ods is None:
        return None
    major, _minor = ods
    if major == 11:    # FB 2.x — major 11 cobre 2.0/2.1/2.5
        return "2.5"
    if major >= 12:    # FB 3.0+ (ODS 12+)
        return "3+"
    return None        # ODS 10 (FB 1.x) — nao suportado pela Shift


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
            "host e database sao obrigatorios para Firebird quando dsn/connection_url nao sao usados."
        )

    return f"{host}/{port}:{database}"


def _normalize_version(value: Any) -> str:
    """Normaliza ``firebird_version`` para "2.5", "3+" ou "auto"."""
    raw = str(value or "").strip().lower()
    if raw in {"2.5", "2", "fb2", "fb2.5", "fdb"}:
        return "2.5"
    if raw in {"auto", "autodetect", "detectar"}:
        return "auto"
    return "3+"


def _normalize_for_compare(p: str) -> str:
    """Normaliza separadores e case para comparacao de prefixo de path."""
    return p.replace("\\", "/").rstrip("/").lower()


def translate_host_path_to_container(
    host_path: str,
    host: str | None = None,
) -> str:
    """Traduz caminho Windows do host para caminho dentro do container.

    Quando o usuario informa o caminho como ele ve no Windows
    (ex: ``C:\\Shift\\Data\\PALACIO.FDB``) e o bind-mount eh
    ``C:\\Shift\\Data -> /firebird/data``, traduzimos para o equivalente
    dentro do container (``/firebird/data/PALACIO.FDB``).

    Estrategia (na ordem):

    1. Path remoto -> preserva (host nao-bundled).
    2. Path ja em ``/firebird/data/...`` -> preserva.
    3. ``FIREBIRD_HOST_MOUNT_ROOT`` setado e e prefixo do path do usuario
       -> remove o prefixo e prefixa ``/firebird/data/``.
       (Cobre ``C:\\Shift\\Data\\X.FDB`` -> ``/firebird/data/X.FDB``.)
    4. Path Windows com letra de drive -> descarta a letra e prefixa
       ``/firebird/data/``. Compat com a convencao antiga onde o mount
       era a raiz do drive (``D:/`` -> ``/firebird/data``).
    5. Outro caso -> preserva.
    """
    if not host_path:
        return host_path

    if not _is_bundled_host(host):
        return host_path

    s = host_path.strip()

    # 2) Ja e caminho do container.
    if s.startswith(_LOCAL_FDB_MOUNT):
        return s

    # 3) Striping pelo mount root explicito (ex: C:\Shift\Data).
    mount_root = os.environ.get("FIREBIRD_HOST_MOUNT_ROOT", "").strip()
    if mount_root and len(mount_root) >= 2:
        root_norm = _normalize_for_compare(mount_root)
        path_norm = s.replace("\\", "/")
        if path_norm.lower().startswith(root_norm + "/"):
            rel = path_norm[len(root_norm):].lstrip("/")
            return f"{_LOCAL_FDB_MOUNT}/{rel}" if rel else _LOCAL_FDB_MOUNT
        if path_norm.lower() == root_norm:
            return _LOCAL_FDB_MOUNT

    # 4) Caminho Windows com letra de drive — fallback / compat antiga.
    if len(s) >= 3 and s[1] == ":" and s[2] in ("\\", "/"):
        rel = s[2:].replace("\\", "/").lstrip("/")
        return f"{_LOCAL_FDB_MOUNT}/{rel}"

    return s


def _resolve_fb3_lib(config: dict[str, Any]) -> str | None:
    """Localiza libfbclient 3.0+ — retorna None se nao encontrar (driver usa default do sistema)."""
    configured = config.get("client_library_path")
    if configured:
        path = Path(str(configured))
        if path.exists():
            return str(path)

    candidates = [
        r"C:\Program Files\Firebird\Firebird_5_0\fbclient.dll",
        r"C:\Program Files\Firebird\Firebird_4_0\fbclient.dll",
        r"C:\Program Files\Firebird\Firebird_3_0\fbclient.dll",
        "/usr/lib/x86_64-linux-gnu/libfbclient.so.2",
        "/usr/lib/libfbclient.so",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def _resolve_fb25_lib(config: dict[str, Any]) -> str | None:
    """Localiza libfbclient 2.5. Procura primeiro o caminho explicito, depois
    o /opt/firebird-2.5/lib do container, e por fim instalacoes Windows locais."""
    configured = config.get("client_library_path")
    if configured:
        path = Path(str(configured))
        if path.exists():
            return str(path)

    candidates = [
        _FB25_LIB_LINUX,
        r"C:\Program Files\Firebird\Firebird_2_5\bin\fbclient.dll",
        r"C:\Program Files (x86)\Firebird\Firebird_2_5\bin\fbclient.dll",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    return None


def _connect_via_firebird_driver(
    config: dict[str, Any],
    secret: dict[str, Any] | None,
) -> Any:
    """Conecta usando o driver moderno (FB 3.0+)."""
    from firebird import driver as fb_driver  # type: ignore[import-untyped]

    client_library = _resolve_fb3_lib(config)
    if client_library:
        fb_driver.driver_config.fb_client_library.value = client_library  # type: ignore[attr-defined]

    kwargs: dict[str, Any] = {
        "database": _build_database_dsn(config),
        "user": config.get("username"),
        "password": (secret or {}).get("password"),
        "charset": config.get("charset") or "WIN1252",
    }
    role = config.get("role") or None
    if role:
        kwargs["role"] = role

    return fb_driver.connect(**kwargs)


def _connect_via_fdb(
    config: dict[str, Any],
    secret: dict[str, Any] | None,
) -> Any:
    """Conecta usando o driver legado fdb (FB 2.5)."""
    import fdb  # type: ignore[import-untyped]

    client_library = _resolve_fb25_lib(config)
    if client_library is None:
        raise RuntimeError(
            "libfbclient 2.5 nao encontrada. Em container, a imagem deve ter "
            f"sido buildada com a lib em {_FB25_LIB_LINUX}. Em desenvolvimento "
            "local, instale Firebird 2.5 ou ajuste client_library_path."
        )

    kwargs: dict[str, Any] = {
        "dsn": _build_database_dsn(config),
        "user": config.get("username"),
        "password": (secret or {}).get("password"),
        "charset": config.get("charset") or "WIN1252",
        "fb_library_name": client_library,
    }
    role = config.get("role") or None
    if role:
        kwargs["role"] = role

    return fdb.connect(**kwargs)


def connect_firebird(
    config: dict[str, Any],
    secret: dict[str, Any] | None,
) -> Any:
    """
    Retorna uma conexao DBAPI ao banco Firebird, escolhendo driver/lib
    conforme ``config["firebird_version"]`` ("2.5", "3+" ou "auto").

    Quando "auto", le o ODS do arquivo .fdb (precisa estar acessivel via
    o bind-mount /firebird/data/) e roteia para fdb (FB 2.5) ou
    firebird-driver (FB 3.0+) automaticamente.

    Parametros lidos de ``config``:
      - host, port, database     — obrigatorios (ou dsn / connection_url)
      - username                 — usuario do banco
      - role                     — role opcional
      - charset                  — charset (padrao: WIN1252)
      - client_library_path      — caminho explicito para fbclient.dll/.so
      - firebird_version         — "2.5", "3+" ou "auto" (default "3+")
      - dsn                      — DSN completo (substitui host/port/database)
      - connection_url           — URL literal passada diretamente ao driver

    ``secret`` deve conter ``password``.
    """
    # Traduz caminho Windows -> container automaticamente, MAS so quando o
    # host alvo e um servidor bundled (firebird25/firebird30). Para host
    # remoto, o usuario manda o path como o servidor remoto enxerga e
    # preservamos literal.
    db_path = config.get("database")
    if db_path:
        translated = translate_host_path_to_container(
            str(db_path), config.get("host")
        )
        if translated != db_path:
            config = {**config, "database": translated}

    version = _normalize_version(config.get("firebird_version"))

    # Resolucao do "auto": le ODS do arquivo (se acessivel) e decide.
    if version == "auto":
        candidate_path = config.get("database")
        resolved = (
            resolve_firebird_version_from_path(str(candidate_path))
            if candidate_path
            else None
        )
        if resolved is None:
            # Se nao conseguir detectar, default seguro: tenta FB 3+
            # primeiro (compativel com a maioria dos servidores modernos).
            version = "3+"
        else:
            version = resolved

    if version == "2.5":
        return _connect_via_fdb(config, secret)
    return _connect_via_firebird_driver(config, secret)
