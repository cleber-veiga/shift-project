"""
Suite de smoke Firebird — baseline da camada de driver.

  - Conectividade FB 2.5 e FB 3.0 via connect_firebird()
  - Auto-deteccao de versao a partir do header do .fdb (ODS)
  - Traducao de path: bundled (Cenario A) traduz, remoto (Cenario B) preserva.
"""

from __future__ import annotations

import pytest

from app.services.firebird_client import (
    connect_firebird,
    resolve_firebird_version_from_path,
    translate_host_path_to_container,
)


pytestmark = pytest.mark.firebird


def test_fb25_ping(fb25_server, fb25_database) -> None:
    """connect_firebird com firebird_version='2.5' abre conexao e responde."""
    config = {
        "host": fb25_server["host"],
        "port": fb25_server["port"],
        "database": fb25_database["container_path"],
        "username": "SYSDBA",
        "firebird_version": "2.5",
        "charset": "WIN1252",
    }
    secret = {"password": "masterkey"}

    conn = connect_firebird(config, secret)
    try:
        cur = conn.cursor()
        cur.execute("select 1 from rdb$database")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1
    finally:
        conn.close()


def test_fb30_ping(fb30_server, fb30_database) -> None:
    """connect_firebird com firebird_version='3+' abre conexao e responde."""
    config = {
        "host": fb30_server["host"],
        "port": fb30_server["port"],
        "database": fb30_database["container_path"],
        "username": "SYSDBA",
        "firebird_version": "3+",
        "charset": "WIN1252",
    }
    secret = {"password": "masterkey"}

    conn = connect_firebird(config, secret)
    try:
        cur = conn.cursor()
        cur.execute("select 1 from rdb$database")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == 1
    finally:
        conn.close()


def test_auto_detect_ods(fb25_database, fb30_database) -> None:
    """ODS 11.x -> '2.5'; ODS 12+ -> '3+'.

    Le o header diretamente do .fdb no bind-mount (sem servidor Firebird).
    """
    fb25_resolved = resolve_firebird_version_from_path(fb25_database["host_path"])
    fb30_resolved = resolve_firebird_version_from_path(fb30_database["host_path"])

    assert fb25_resolved == "2.5", f"esperado '2.5' para FB 2.5 .fdb, veio {fb25_resolved!r}"
    assert fb30_resolved == "3+", f"esperado '3+' para FB 3.0 .fdb, veio {fb30_resolved!r}"


def test_path_translation_bundled() -> None:
    """Cenario A: host bundled -> path Windows e reescrito para /firebird/data."""
    assert (
        translate_host_path_to_container(r"D:\X.FDB", "firebird25")
        == "/firebird/data/X.FDB"
    )
    assert (
        translate_host_path_to_container(r"C:\Data\Sub\Y.FDB", "firebird30")
        == "/firebird/data/Data/Sub/Y.FDB"
    )
    # Path ja no formato container — passa direto.
    assert (
        translate_host_path_to_container("/firebird/data/Z.FDB", "firebird25")
        == "/firebird/data/Z.FDB"
    )
    # Host vazio = auto-detect via mount local — assume bundled.
    assert (
        translate_host_path_to_container(r"D:\X.FDB", None)
        == "/firebird/data/X.FDB"
    )


def test_path_translation_remote() -> None:
    """Cenario B: host remoto -> path preservado literal."""
    # Servidor Firebird no Windows host do cliente.
    assert (
        translate_host_path_to_container(r"D:\X.FDB", "host.docker.internal")
        == r"D:\X.FDB"
    )
    # IP externo.
    assert (
        translate_host_path_to_container(r"C:\Sistemas\X.FDB", "192.168.1.50")
        == r"C:\Sistemas\X.FDB"
    )
    # FQDN.
    assert (
        translate_host_path_to_container("/var/fb/X.FDB", "db.empresa.com")
        == "/var/fb/X.FDB"
    )
