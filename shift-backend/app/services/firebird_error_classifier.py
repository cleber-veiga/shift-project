"""
Classifica excecoes de drivers Firebird (firebird-driver / fdb / sockets)
em uma error_class estavel + hint PT-BR acionavel.

Estrategia: lista ordenada de matchers (do mais especifico ao mais generico),
matcheando por **substring** na mensagem ou por **tipo** da excecao. Substring
e mais estavel entre versoes do que numero de erro Firebird interno.
"""

from __future__ import annotations

import socket
from collections.abc import Callable

# (matcher, error_class, hint_template). hint_template usa .format(...)
# com host/port/database; campos ausentes nao quebram (kwargs extras vao
# pra format mas nao sao obrigatorios na string).
_Matcher = Callable[[Exception, str], bool]


def _has(needle: str) -> _Matcher:
    n = needle.lower()
    return lambda exc, msg: n in msg


def _is_type(*types: type[BaseException]) -> _Matcher:
    return lambda exc, msg: isinstance(exc, types)


_RULES: list[tuple[_Matcher, str, str]] = [
    # DNS
    (
        _is_type(socket.gaierror),
        "dns_failure",
        "Nao foi possivel resolver o host '{host}'. Verifique se o nome esta "
        "correto. Se esta usando 'host.docker.internal', confirme que o backend "
        "foi iniciado com a configuracao de rede correta.",
    ),
    # TCP recusado
    (
        _is_type(ConnectionRefusedError),
        "port_closed",
        "Conexao recusada na porta {port}. Verifique se o servidor Firebird "
        "esta rodando e ouvindo nessa porta. No Windows, libere a porta no "
        "Firewall.",
    ),
    (
        _has("connection refused"),
        "port_closed",
        "Conexao recusada na porta {port}. Verifique se o servidor Firebird "
        "esta rodando e ouvindo nessa porta. No Windows, libere a porta no "
        "Firewall.",
    ),
    # TCP timeout / inalcancavel
    (
        _is_type(TimeoutError, socket.timeout),
        "network_unreachable",
        "Tempo esgotado ao tentar alcancar {host}:{port}. Verifique "
        "conectividade de rede e firewall.",
    ),
    (
        _has("timed out"),
        "network_unreachable",
        "Tempo esgotado ao tentar alcancar {host}:{port}. Verifique "
        "conectividade de rede e firewall.",
    ),
    # ODS incompativel — checa antes de "I/O error" porque a mensagem real do
    # FB e tipo: "I/O error during 'open O_RDWR' ... unsupported on-disk structure".
    (
        _has("unsupported on-disk structure"),
        "wrong_ods",
        "O arquivo .fdb foi criado em uma versao de Firebird incompativel com "
        "o servidor. Selecione 'Firebird 2.5' (se ODS 11) ou use o servidor "
        "bundled da Shift.",
    ),
    (
        _has("ods"),
        "wrong_ods",
        "O arquivo .fdb foi criado em uma versao de Firebird incompativel com "
        "o servidor. Selecione 'Firebird 2.5' (se ODS 11) ou use o servidor "
        "bundled da Shift.",
    ),
    # Wire protocol mismatch (FB 3+ com WireCrypt=Required)
    (
        _has("wirecrypt"),
        "wire_protocol_mismatch",
        "Incompatibilidade de criptografia de protocolo. Cliente FB 2.5 nao "
        "conecta em servidor FB 3+ com WireCrypt=Required. Configure "
        "WireCrypt=Enabled no firebird.conf do servidor.",
    ),
    (
        _has("wire encryption"),
        "wire_protocol_mismatch",
        "Incompatibilidade de criptografia de protocolo. Cliente FB 2.5 nao "
        "conecta em servidor FB 3+ com WireCrypt=Required. Configure "
        "WireCrypt=Enabled no firebird.conf do servidor.",
    ),
    # Auth — checa "your user name" antes de "password" porque a mensagem
    # tipica do FB e "Your user name and password are not defined".
    (
        _has("your user name and password are not defined"),
        "auth_failed",
        "Usuario ou senha invalidos.",
    ),
    (
        _has("login"),
        "auth_failed",
        "Usuario ou senha invalidos.",
    ),
    (
        _has("password"),
        "auth_failed",
        "Usuario ou senha invalidos.",
    ),
    # Charset — checa antes de "bad parameters" porque a mensagem mais
    # comum e "bad parameters on attach or create database ... charset".
    (
        _has("charset"),
        "charset_mismatch",
        "Charset nao suportado. Para ERPs brasileiros, use WIN1252 ou ISO8859_1.",
    ),
    (
        _has("bad parameters on attach"),
        "charset_mismatch",
        "Charset nao suportado. Para ERPs brasileiros, use WIN1252 ou ISO8859_1.",
    ),
    # Handle invalido / conexao sem contexto. Driver fdb (FB 2.5) reporta
    # '-904 invalid database handle (no active connection)' quando o attach
    # falhou mas o motivo real ficou oculto. Tipico de mismatch de versao
    # (cliente FB 2.5 contra servidor FB 3+) ou libfbclient mal-resolvida.
    (
        _has("no active connection"),
        "connection_lost",
        "O driver perdeu o handle ao iniciar transacao — geralmente o "
        "servidor recusou o attach mas o motivo real ficou oculto. "
        "Verifique: (a) host compativel com a versao escolhida (Firebird 2.5 "
        "-> host firebird25; Firebird 3+ -> host firebird30); (b) logs do "
        "servidor com 'docker compose logs firebird25' ou 'firebird30'; "
        "(c) tente 'Auto-detectar' na versao para o backend rotear pelo ODS.",
    ),
    (
        _has("invalid database handle"),
        "connection_lost",
        "O driver perdeu o handle ao iniciar transacao — geralmente o "
        "servidor recusou o attach mas o motivo real ficou oculto. "
        "Verifique: (a) host compativel com a versao escolhida (Firebird 2.5 "
        "-> host firebird25; Firebird 3+ -> host firebird30); (b) logs do "
        "servidor com 'docker compose logs firebird25' ou 'firebird30'; "
        "(c) tente 'Auto-detectar' na versao para o backend rotear pelo ODS.",
    ),
    # Lock / permissao no .fdb — outro processo (FB Server local, DBeaver
    # com sessao aberta, antivirus) esta segurando o arquivo. Mensagem
    # tipica: 'no permission for read-write access to database ...
    # IProvider::attachDatabase failed when loading mapping cache'.
    (
        _has("no permission for read-write access"),
        "database_locked",
        "Outro processo esta segurando o arquivo .fdb com lock exclusivo. "
        "Causa comum: o Firebird Server local do Windows esta rodando e "
        "bloqueando o arquivo. Pare o servico (`Stop-Service FirebirdServerDefaultInstance` "
        "no PowerShell admin) OU use uma copia separada do .fdb so para a Shift.",
    ),
    (
        _has("loading mapping cache"),
        "database_locked",
        "Outro processo esta segurando o arquivo .fdb com lock exclusivo. "
        "Causa comum: o Firebird Server local do Windows esta rodando e "
        "bloqueando o arquivo. Pare o servico (`Stop-Service FirebirdServerDefaultInstance` "
        "no PowerShell admin) OU use uma copia separada do .fdb so para a Shift.",
    ),
    # Path / arquivo .fdb nao encontrado
    (
        _has("i/o error"),
        "path_not_found",
        "Arquivo .fdb nao encontrado no caminho '{database}'. Verifique se "
        "o caminho esta correto na perspectiva do servidor Firebird "
        "(caminho do Windows se servidor esta no Windows).",
    ),
    (
        _has("file not found"),
        "path_not_found",
        "Arquivo .fdb nao encontrado no caminho '{database}'. Verifique se "
        "o caminho esta correto na perspectiva do servidor Firebird "
        "(caminho do Windows se servidor esta no Windows).",
    ),
    (
        _has("cannot find"),
        "path_not_found",
        "Arquivo .fdb nao encontrado no caminho '{database}'. Verifique se "
        "o caminho esta correto na perspectiva do servidor Firebird "
        "(caminho do Windows se servidor esta no Windows).",
    ),
    (
        _has("no such file"),
        "path_not_found",
        "Arquivo .fdb nao encontrado no caminho '{database}'. Verifique se "
        "o caminho esta correto na perspectiva do servidor Firebird "
        "(caminho do Windows se servidor esta no Windows).",
    ),
]


_NOT_FIREBIRD_HINT = (
    "A porta {port} respondeu, mas nao parece ser um servidor Firebird."
)
_UNKNOWN_HINT = "Falha nao classificada. Detalhes tecnicos: {error_msg}"


def classify(
    exc: Exception,
    *,
    host: str = "",
    port: int = 0,
    database: str = "",
) -> tuple[str, str]:
    """Devolve (error_class, hint_pt_br) para a excecao recebida.

    Procura na mensagem da excecao e em sua __cause__/__context__ (cadeia).
    Hint usa interpolacao com host/port/database.
    """
    msg = _collect_message(exc).lower()

    for matcher, error_class, hint_template in _RULES:
        try:
            if matcher(exc, msg):
                hint = hint_template.format(
                    host=host or "?",
                    port=port or "?",
                    database=database or "?",
                    error_msg=_safe_str(exc),
                )
                return error_class, hint
        except Exception:  # noqa: BLE001 — matcher defeituoso nao quebra classify
            continue

    return "unknown", _UNKNOWN_HINT.format(error_msg=_safe_str(exc))


def not_firebird_hint(port: int) -> str:
    """Hint dedicado para o caso de porta aberta mas resposta nao-FB."""
    return _NOT_FIREBIRD_HINT.format(port=port or "?")


def _collect_message(exc: BaseException) -> str:
    """Concatena a mensagem da excecao e da __cause__/__context__."""
    parts: list[str] = []
    seen: set[int] = set()
    cur: BaseException | None = exc
    depth = 0
    while cur is not None and depth < 5 and id(cur) not in seen:
        seen.add(id(cur))
        parts.append(_safe_str(cur))
        cur = cur.__cause__ or cur.__context__
        depth += 1
    return " | ".join(p for p in parts if p)


def _safe_str(exc: BaseException) -> str:
    try:
        return str(exc)
    except Exception:  # noqa: BLE001
        return repr(exc)
