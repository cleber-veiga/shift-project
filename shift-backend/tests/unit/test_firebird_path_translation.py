"""
Testes unitarios da regra de traducao de path Firebird.

Regra: traduzir D:\\X.FDB -> /firebird/data/X.FDB SOMENTE quando o host
alvo e um servidor bundled (firebird25/firebird30) ou ausente. Para host
remoto (host.docker.internal, IP, FQDN, localhost) o path e preservado.
"""

from __future__ import annotations

import pytest

from app.services.firebird_client import translate_host_path_to_container


@pytest.mark.parametrize(
    "host,input_path,expected",
    [
        # Sem host informado -> assume bundled, traduz.
        (None, r"D:\X.FDB", "/firebird/data/X.FDB"),
        ("", r"D:\X.FDB", "/firebird/data/X.FDB"),
        # Servidores bundled -> traduz.
        ("firebird25", r"D:\Data\X.FDB", "/firebird/data/Data/X.FDB"),
        ("firebird30", "C:/db/X.FDB", "/firebird/data/db/X.FDB"),
        # Variantes de bundled com dominio (compose com network alias).
        ("firebird25.shift-net", r"D:\X.FDB", "/firebird/data/X.FDB"),
        ("FIREBIRD30", r"D:\X.FDB", "/firebird/data/X.FDB"),
        # Hosts remotos -> preserva path literal.
        ("host.docker.internal", r"D:\X.FDB", r"D:\X.FDB"),
        ("192.168.1.50", r"C:\Sistemas\X.FDB", r"C:\Sistemas\X.FDB"),
        ("db.empresa.com", "/var/fb/X.FDB", "/var/fb/X.FDB"),
        # localhost e tratado como host remoto — usuario pensa "minha
        # maquina", nao "container". Bundled e explicito (firebird25/30).
        ("localhost", r"D:\X.FDB", r"D:\X.FDB"),
        # Bundled + path ja em formato container -> idempotente.
        ("firebird25", "/firebird/data/X.FDB", "/firebird/data/X.FDB"),
        # Bundled + path relativo (sem letra de drive) -> passa sem alterar.
        ("firebird25", "relative/path.fdb", "relative/path.fdb"),
    ],
)
def test_translate_host_path(host: str | None, input_path: str, expected: str) -> None:
    assert translate_host_path_to_container(input_path, host) == expected


def test_empty_path_passes_through() -> None:
    assert translate_host_path_to_container("", "firebird25") == ""
    assert translate_host_path_to_container("", "host.docker.internal") == ""
