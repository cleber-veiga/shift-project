"""
Cenario A — servidor Firebird bundled (firebird25 / firebird30).

Valida:
  - Conectividade end-to-end via ambos servidores bundled.
  - Path translation reescreve `D:\\X.FDB` -> `/firebird/data/X.FDB` quando
    host e bundled (verificado via mock do driver, sem precisar resolver
    'firebird25' DNS no test runner).
  - Auto-roteamento por ODS escolhe driver/servidor certo.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.firebird_client import (
    connect_firebird,
    resolve_firebird_version_from_path,
)


pytestmark = pytest.mark.firebird


def _config_for(server: dict, db_path: str, version: str) -> dict:
    return {
        "host": server["host"],
        "port": server["port"],
        "database": db_path,
        "username": "SYSDBA",
        "firebird_version": version,
        "charset": "WIN1252",
    }


def test_a_fb25_via_compose_network(fb25_server, fb25_database) -> None:
    """E2E: connect_firebird() liga em FB 2.5 e responde a select 1.

    Topologia compose: backend -> firebird25:3050. Aqui a fixture expoe a
    porta em 127.0.0.1:<efemera>; a verificacao de que o hostname
    'firebird25' faz a tradução de path correta esta no teste de mock
    abaixo (test_a_path_translation_with_bundled_host).
    """
    config = _config_for(fb25_server, fb25_database["container_path"], "2.5")
    conn = connect_firebird(config, {"password": "masterkey"})
    try:
        cur = conn.cursor()
        cur.execute("select 1 from rdb$database")
        row = cur.fetchone()
        assert row is not None and row[0] == 1
    finally:
        conn.close()


def test_a_fb30_via_compose_network(fb30_server, fb30_database) -> None:
    """E2E: connect_firebird() liga em FB 3.0 e responde a select 1."""
    config = _config_for(fb30_server, fb30_database["container_path"], "3+")
    conn = connect_firebird(config, {"password": "masterkey"})
    try:
        cur = conn.cursor()
        cur.execute("select 1 from rdb$database")
        row = cur.fetchone()
        assert row is not None and row[0] == 1
    finally:
        conn.close()


def test_a_path_translation_with_bundled_host() -> None:
    """connect_firebird com host=firebird25 reescreve path Windows ANTES de
    chamar o driver. Mock do _connect_via_fdb captura o config final.

    Sem isso, nao da pra validar a topologia 'host=firebird25' end-to-end
    no test runner local (o nome firebird25 so resolve dentro da rede compose).
    """
    captured = {}

    def fake_connect(config, secret):
        captured["database"] = config.get("database")
        captured["host"] = config.get("host")
        return type("FakeConn", (), {"cursor": lambda self: None, "close": lambda self: None})()

    config = {
        "host": "firebird25",
        "port": 3050,
        "database": r"D:\Data\X.FDB",
        "username": "SYSDBA",
        "firebird_version": "2.5",
    }
    with patch("app.services.firebird_client._connect_via_fdb", side_effect=fake_connect):
        connect_firebird(config, {"password": "x"})

    assert captured["host"] == "firebird25"
    assert captured["database"] == "/firebird/data/Data/X.FDB", (
        f"path nao foi traduzido para o mount do container: {captured['database']!r}"
    )


def test_a_auto_routing_by_ods(fb25_database, fb30_database) -> None:
    """firebird_version='auto' deve resolver para '2.5' (ODS 11) e '3+' (ODS 12)
    com base no header dos arquivos .fdb auto-criados pelos containers.

    Nota: validamos a funcao de roteamento por ODS isoladamente. O E2E
    auto-resolve+connect requer que o backend e o FB server compartilhem o
    MESMO caminho de filesystem (`/firebird/data/...` em ambos via mount),
    o que so e possivel rodando os testes dentro do container backend —
    nao no host runner. Nesses ambientes mistos o roteamento por ODS cai
    no default seguro '3+' (documentado em firebird_client.connect_firebird).
    """
    fb25_resolved = resolve_firebird_version_from_path(fb25_database["host_path"])
    fb30_resolved = resolve_firebird_version_from_path(fb30_database["host_path"])

    assert fb25_resolved == "2.5", (
        f"esperado '2.5' para .fdb gerado pelo FB 2.5, veio {fb25_resolved!r}"
    )
    assert fb30_resolved == "3+", (
        f"esperado '3+' para .fdb gerado pelo FB 3.0, veio {fb30_resolved!r}"
    )
