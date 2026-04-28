"""
Testes de integracao do pipeline de diagnostico Firebird.

Cobre 3 cenarios de falha (DNS, TCP, auth) end-to-end. Skip explicito
quando Docker indisponivel (via fixtures fb30_server).
"""

from __future__ import annotations

import socket

import pytest

from app.services.firebird_diagnostics import diagnose


pytestmark = pytest.mark.firebird


def _find_unused_port() -> int:
    """Acha uma porta TCP que esta fechada (sem listener) no localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    return port


def test_diagnose_wrong_password(fb30_server, fb30_database) -> None:
    """Senha errada -> auth_query falha com error_class='auth_failed'."""
    steps = diagnose(
        host=fb30_server["host"],
        port=fb30_server["port"],
        database=fb30_database["container_path"],
        username="SYSDBA",
        password="senha-errada-com-certeza",
        firebird_version="3+",
        timeout_per_step=3.0,
    )

    # As 3 primeiras etapas (DNS, TCP, greeting) devem passar.
    assert len(steps) == 4, f"esperado 4 etapas, veio {[s['stage'] for s in steps]}"
    assert all(s["ok"] for s in steps[:3]), (
        f"DNS/TCP/greeting nao deveriam falhar: {steps[:3]}"
    )

    auth = steps[3]
    assert auth["stage"] == "auth_query"
    assert auth["ok"] is False
    assert auth["error_class"] == "auth_failed", (
        f"esperado auth_failed, veio {auth['error_class']!r} (msg={auth['error_msg']!r})"
    )
    assert auth["hint"] == "Usuario ou senha invalidos."


def test_diagnose_dns_failure() -> None:
    """Host inexistente -> falha imediata em DNS, etapas seguintes nao rodam."""
    steps = diagnose(
        host="host-que-nao-existe-shift-test.invalid",
        port=3050,
        database="qualquer.fdb",
        username="SYSDBA",
        password="x",
        timeout_per_step=3.0,
    )

    assert len(steps) == 1, f"deveria parar em DNS, veio {[s['stage'] for s in steps]}"
    dns = steps[0]
    assert dns["stage"] == "dns"
    assert dns["ok"] is False
    assert dns["error_class"] == "dns_failure"
    assert "host-que-nao-existe-shift-test.invalid" in (dns["hint"] or "")


def test_diagnose_port_closed() -> None:
    """Porta sem listener -> DNS ok, TCP falha com port_closed."""
    port = _find_unused_port()
    steps = diagnose(
        host="127.0.0.1",
        port=port,
        database="qualquer.fdb",
        username="SYSDBA",
        password="x",
        timeout_per_step=3.0,
    )

    assert len(steps) == 2, f"deveria parar em TCP, veio {[s['stage'] for s in steps]}"
    assert steps[0]["stage"] == "dns" and steps[0]["ok"] is True
    tcp = steps[1]
    assert tcp["stage"] == "tcp"
    assert tcp["ok"] is False
    # No Linux/Windows, conexao a porta fechada em loopback gera ECONNREFUSED.
    assert tcp["error_class"] == "port_closed", (
        f"esperado port_closed, veio {tcp['error_class']!r} (msg={tcp['error_msg']!r})"
    )
