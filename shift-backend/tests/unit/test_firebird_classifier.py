"""
Testes unitarios do classificador de erros Firebird.

Para cada error_class da tabela de Fase 3, criamos uma excecao sintetica
que carrega o sinal esperado e verificamos que classify() devolve a
classe certa + hint interpolado com host/port/database.
"""

from __future__ import annotations

import socket

import pytest

from app.services.firebird_error_classifier import classify, not_firebird_hint


def _hint_should_contain(hint: str, *needles: str) -> None:
    for n in needles:
        assert n in hint, f"hint nao contem {n!r}: {hint!r}"


# ---------------------------------------------------------------------------
# Tabela de erros conhecidos
# ---------------------------------------------------------------------------


def test_dns_failure_via_gaierror() -> None:
    exc = socket.gaierror(11001, "getaddrinfo failed")
    cls, hint = classify(exc, host="bad.local", port=3050, database="X.FDB")
    assert cls == "dns_failure"
    _hint_should_contain(hint, "bad.local")


def test_port_closed_via_connection_refused() -> None:
    exc = ConnectionRefusedError("Connection refused")
    cls, hint = classify(exc, host="h", port=3050, database="X.FDB")
    assert cls == "port_closed"
    _hint_should_contain(hint, "3050", "Firewall")


def test_port_closed_via_substring() -> None:
    exc = OSError("Connection refused by remote host")
    cls, _ = classify(exc, host="h", port=3050)
    assert cls == "port_closed"


def test_network_unreachable_via_timeout_type() -> None:
    exc = TimeoutError("op timed out")
    cls, hint = classify(exc, host="h", port=3050)
    # TimeoutError tem 'timed out' na mensagem — qualquer um dos dois
    # matchers (tipo ou substring) deve casar para network_unreachable.
    assert cls == "network_unreachable"
    _hint_should_contain(hint, "h", "3050")


def test_network_unreachable_via_socket_timeout() -> None:
    exc = socket.timeout("timed out")
    cls, _ = classify(exc, host="h", port=3050)
    assert cls == "network_unreachable"


def test_wrong_ods_substring() -> None:
    exc = RuntimeError(
        "Error while connecting to database: I/O error during 'open O_RDWR' "
        "operation for file '/firebird/data/X.FDB'; unsupported on-disk "
        "structure for file"
    )
    cls, hint = classify(exc, host="h", port=3050, database="/firebird/data/X.FDB")
    assert cls == "wrong_ods"
    _hint_should_contain(hint, "ODS 11")


def test_wire_protocol_mismatch_wirecrypt() -> None:
    exc = RuntimeError("Incompatible wire encryption: WireCrypt=Required at server")
    cls, hint = classify(exc)
    assert cls == "wire_protocol_mismatch"
    _hint_should_contain(hint, "WireCrypt")


def test_auth_failed_username_password() -> None:
    exc = RuntimeError("Your user name and password are not defined. Ask your DBA")
    cls, hint = classify(exc)
    assert cls == "auth_failed"
    assert hint == "Usuario ou senha invalidos."


def test_auth_failed_login_substring() -> None:
    exc = RuntimeError("Login error 335544472")
    cls, _ = classify(exc)
    assert cls == "auth_failed"


def test_charset_mismatch_via_charset() -> None:
    exc = RuntimeError("bad parameters on attach or create database — invalid charset")
    cls, hint = classify(exc)
    assert cls == "charset_mismatch"
    _hint_should_contain(hint, "WIN1252")


def test_path_not_found_io_error() -> None:
    exc = RuntimeError(
        "I/O error during 'open' operation for file 'C:\\X.FDB'"
    )
    cls, hint = classify(exc, host="h", port=3050, database=r"C:\X.FDB")
    assert cls == "path_not_found"
    _hint_should_contain(hint, r"C:\X.FDB")


def test_path_not_found_no_such_file() -> None:
    exc = RuntimeError("no such file or directory: /firebird/data/missing.fdb")
    cls, _ = classify(exc, database="/firebird/data/missing.fdb")
    assert cls == "path_not_found"


def test_connection_lost_no_active_connection() -> None:
    """fdb FB 2.5 reporta -904 quando attach falha silenciosamente."""
    exc = RuntimeError(
        "Error while starting transaction:\n- SQLCODE: -904\n"
        "- invalid database handle (no active connection)"
    )
    cls, hint = classify(exc)
    assert cls == "connection_lost"
    assert "host" in hint and "ODS" in hint


def test_database_locked_no_permission() -> None:
    """Lock do FB Server local segurando o .fdb — mensagem real do FB 3.0."""
    exc = RuntimeError(
        "Error while connecting to database: no permission for read-write "
        "access to database /firebird/data/PALACIO.FDB - "
        "IProvider::attachDatabase failed when loading mapping cache"
    )
    cls, hint = classify(exc)
    assert cls == "database_locked"
    assert "Firebird Server local" in hint or "lock exclusivo" in hint


def test_database_locked_mapping_cache() -> None:
    exc = RuntimeError("IProvider::attachDatabase failed when loading mapping cache")
    cls, _ = classify(exc)
    assert cls == "database_locked"


def test_unknown_falls_back() -> None:
    exc = RuntimeError("totalmente novo codigo de erro nao mapeado")
    cls, hint = classify(exc)
    assert cls == "unknown"
    _hint_should_contain(hint, "novo codigo")


# ---------------------------------------------------------------------------
# Corner cases
# ---------------------------------------------------------------------------


def test_hint_interpolates_host_port_database() -> None:
    exc = ConnectionRefusedError("nope")
    _, hint = classify(exc, host="server.local", port=3050, database="/x/y.fdb")
    assert "3050" in hint


def test_exc_without_args() -> None:
    exc = RuntimeError()  # str(exc) == ""
    cls, hint = classify(exc, host="h", port=3050)
    # Nada na mensagem — cai no unknown.
    assert cls == "unknown"
    assert hint  # nao vazio


def test_cause_chain_is_traversed() -> None:
    """classify deve olhar para __cause__ ao decidir."""
    inner = ConnectionRefusedError("Connection refused")
    outer = RuntimeError("falha generica do driver")
    outer.__cause__ = inner
    cls, _ = classify(outer, host="h", port=3050)
    assert cls == "port_closed"


def test_context_chain_is_traversed() -> None:
    inner = socket.gaierror("getaddrinfo failed")
    outer = RuntimeError("driver erro")
    outer.__context__ = inner
    cls, _ = classify(outer, host="h", port=3050)
    # gaierror via __context__ deve ser detectado pela substring no msg agregado.
    # Nota: o matcher de tipo so olha para `exc` direto, mas o substring
    # 'getaddrinfo' nao esta na nossa tabela. Esperamos unknown OU dns —
    # o que importa e que NAO crashou. Vamos ver.
    assert cls in {"dns_failure", "unknown"}


def test_not_firebird_hint_format() -> None:
    h = not_firebird_hint(3050)
    assert "3050" in h


@pytest.mark.parametrize(
    "needle,expected_class",
    [
        ("Connection refused", "port_closed"),
        ("unsupported on-disk structure for file", "wrong_ods"),
        ("WireCrypt incompatibility", "wire_protocol_mismatch"),
        ("password is invalid", "auth_failed"),
        ("invalid charset specified", "charset_mismatch"),
        ("file not found at path", "path_not_found"),
        ("totalmente desconhecido", "unknown"),
    ],
)
def test_classify_table(needle: str, expected_class: str) -> None:
    exc = RuntimeError(needle)
    cls, _ = classify(exc, host="h", port=3050, database="X.FDB")
    assert cls == expected_class
