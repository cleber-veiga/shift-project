"""
Pipeline de diagnostico de conectividade Firebird.

Roda 4 etapas em ordem (DNS -> TCP -> greeting -> auth_query) e para na
primeira falha, devolvendo a etapa que quebrou + hint PT-BR acionavel.
Cada etapa registra latencia e error_class estavel via firebird_error_classifier.
"""

from __future__ import annotations

import socket
import time
from typing import Literal, TypedDict

from app.core.logging import get_logger
from app.services.firebird_error_classifier import classify, not_firebird_hint

logger = get_logger(__name__)


Stage = Literal["dns", "tcp", "greeting", "auth_query"]


class DiagnosticStep(TypedDict):
    stage: Stage
    ok: bool
    latency_ms: int | None
    error_class: str | None
    error_msg: str | None
    hint: str | None


def _now() -> float:
    return time.monotonic()


def _ms_since(t0: float) -> int:
    return int((_now() - t0) * 1000)


def _log_step(step: DiagnosticStep, host: str, port: int) -> None:
    """Loga cada etapa em formato estruturado. Nao loga senha — somente
    campos do step + identificacao do alvo."""
    logger.info(
        "firebird.diagnose.step",
        stage=step["stage"],
        ok=step["ok"],
        latency_ms=step["latency_ms"],
        error_class=step["error_class"],
        host=host,
        port=port,
    )


def _step(
    stage: Stage,
    ok: bool,
    latency_ms: int | None,
    error_class: str | None = None,
    error_msg: str | None = None,
    hint: str | None = None,
) -> DiagnosticStep:
    return {
        "stage": stage,
        "ok": ok,
        "latency_ms": latency_ms,
        "error_class": error_class,
        "error_msg": error_msg,
        "hint": hint,
    }


def _probe_firebird_greeting(sock: socket.socket, timeout: float) -> tuple[bool, str | None]:
    """Envia op_connect minimo e checa se a resposta NAO e de outro protocolo.

    Wire protocol FB: op_connect = 1 (4 bytes BE). Pacote malformado pode:
      - Provocar op_reject/op_response (alguns servidores)
      - Fechar o socket silenciosamente (FB 3.0+ tipicamente)
      - Aguardar mais dados (timeout do nosso lado)

    So flagamos `not_firebird` quando reconhecemos POSITIVAMENTE outro
    protocolo (HTTP, SSH, SMTP). Caso contrario passa adiante e deixa
    auth_query confirmar — qualquer falha real aparece la com mensagem
    do driver.
    """
    sock.settimeout(timeout)
    try:
        # op_connect (4 BE) + padding zerado.
        sock.sendall(b"\x00\x00\x00\x01" + b"\x00" * 16)
        data = sock.recv(64)
    except (socket.timeout, OSError):
        # Timeout ou socket fechado — comportamento ambiguo. FB 3.0
        # frequentemente fecha a conexao sem responder a packets malformados.
        return True, None

    if not data:
        # Conexao fechada sem resposta — tambem ambiguo, deixa passar.
        return True, None

    head = data[:8]
    if head.startswith((b"HTTP/", b"GET ", b"POST", b"SSH-", b"220 ")):
        return False, f"resposta nao-Firebird: {head!r}"
    return True, None


def _run_dns(host: str) -> tuple[DiagnosticStep, str | None]:
    """Etapa 1: resolucao DNS. Retorna (step, ip_resolvido_ou_None)."""
    t0 = _now()
    try:
        ip = socket.gethostbyname(host)
    except socket.gaierror as exc:
        ec, hint = classify(exc, host=host)
        return _step("dns", False, _ms_since(t0), ec, str(exc), hint), None
    return _step("dns", True, _ms_since(t0)), ip


def _run_tcp(
    ip: str,
    host: str,
    port: int,
    timeout: float,
) -> tuple[DiagnosticStep, socket.socket | None]:
    """Etapa 2: TCP connect. Retorna (step, socket_aberto_ou_None)."""
    t0 = _now()
    try:
        sock = socket.create_connection((ip, port), timeout=timeout)
    except (ConnectionRefusedError, TimeoutError, socket.timeout, OSError) as exc:
        ec, hint = classify(exc, host=host, port=port)
        return _step("tcp", False, _ms_since(t0), ec, str(exc), hint), None
    return _step("tcp", True, _ms_since(t0)), sock


def _run_greeting(
    sock: socket.socket,
    host: str,
    port: int,
    timeout: float,
) -> DiagnosticStep:
    """Etapa 3: probe op_connect. Sempre fecha o socket no final."""
    t0 = _now()
    try:
        ok, why = _probe_firebird_greeting(sock, timeout)
    finally:
        try:
            sock.close()
        except Exception:  # noqa: BLE001
            pass

    if ok:
        return _step("greeting", True, _ms_since(t0))
    return _step(
        "greeting",
        False,
        _ms_since(t0),
        error_class="not_firebird",
        error_msg=why,
        hint=not_firebird_hint(port),
    )


def _run_auth_query(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    firebird_version: str,
    charset: str,
    role: str | None,
) -> DiagnosticStep:
    """Etapa 4: auth + select 1 from rdb$database via connect_firebird."""
    from app.services.firebird_client import connect_firebird

    config: dict[str, object] = {
        "host": host,
        "port": port,
        "database": database,
        "username": username,
        "firebird_version": firebird_version,
        "charset": charset,
    }
    if role:
        config["role"] = role
    secret = {"password": password}

    t0 = _now()
    fb_conn = None
    try:
        fb_conn = connect_firebird(config=config, secret=secret)
        cur = fb_conn.cursor()
        cur.execute("select 1 from rdb$database")
        cur.fetchone()
        cur.close()
    except Exception as exc:  # noqa: BLE001 — diagnostic engloba qualquer erro
        ec, hint = classify(exc, host=host, port=port, database=database)
        return _step("auth_query", False, _ms_since(t0), ec, str(exc), hint)
    finally:
        if fb_conn is not None:
            try:
                fb_conn.close()
            except Exception:  # noqa: BLE001
                pass

    return _step("auth_query", True, _ms_since(t0))


def diagnose(
    host: str,
    port: int,
    database: str,
    username: str,
    password: str,
    firebird_version: str = "3+",
    charset: str = "WIN1252",
    role: str | None = None,
    timeout_per_step: float = 3.0,
) -> list[DiagnosticStep]:
    """Roda o pipeline em ordem; para na primeira falha.

    Devolve a lista das etapas executadas — etapas posteriores a uma falha
    nao sao executadas, entao a lista pode ter 1, 2, 3 ou 4 itens.
    Senha NUNCA aparece em logs nem nos campos retornados.
    """
    steps: list[DiagnosticStep] = []

    dns_step, ip = _run_dns(host)
    steps.append(dns_step)
    _log_step(dns_step, host, port)
    if not dns_step["ok"] or ip is None:
        return steps

    tcp_step, sock = _run_tcp(ip, host, port, timeout_per_step)
    steps.append(tcp_step)
    _log_step(tcp_step, host, port)
    if not tcp_step["ok"] or sock is None:
        return steps

    greeting_step = _run_greeting(sock, host, port, timeout_per_step)
    steps.append(greeting_step)
    _log_step(greeting_step, host, port)
    if not greeting_step["ok"]:
        return steps

    auth_step = _run_auth_query(
        host=host,
        port=port,
        database=database,
        username=username,
        password=password,
        firebird_version=firebird_version,
        charset=charset,
        role=role,
    )
    steps.append(auth_step)
    _log_step(auth_step, host, port)
    return steps


def overall_ok(steps: list[DiagnosticStep]) -> bool:
    return len(steps) == 4 and all(s["ok"] for s in steps)


def first_failure(steps: list[DiagnosticStep]) -> DiagnosticStep | None:
    return next((s for s in steps if not s["ok"]), None)
