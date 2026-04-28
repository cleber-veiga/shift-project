"""
Cenario C — servidor Firebird incompativel com ODS do arquivo.

Ex: cliente apontou um .fdb ODS 11 (FB 2.5) para o servidor firebird30
(FB 3.0+). Engine recusa com 'unsupported on-disk structure'. A Shift
deve detectar via auto-routing e cair no servidor bundled compativel.
"""

from __future__ import annotations

import pytest

from app.services.firebird_client import (
    connect_firebird,
    resolve_firebird_version_from_path,
)
from app.services.firebird_diagnostics import diagnose


pytestmark = pytest.mark.firebird


def test_c_fb4_rejects_ods11(fb30_server, fb25_db_in_fb30_mount) -> None:
    """FB 3.0+ atachando .fdb ODS 11 -> diagnose retorna wrong_ods."""
    steps = diagnose(
        host=fb30_server["host"],
        port=fb30_server["port"],
        database=fb25_db_in_fb30_mount["container_path"],
        username="SYSDBA",
        password="masterkey",
        firebird_version="3+",
        timeout_per_step=3.0,
    )

    assert len(steps) == 4, [s["stage"] for s in steps]
    auth = steps[3]
    assert auth["ok"] is False, "FB 3.0 deveria recusar ODS 11"
    assert auth["error_class"] == "wrong_ods", (
        f"esperado wrong_ods, veio {auth['error_class']!r} (msg={auth['error_msg']!r})"
    )


def test_c_fallback_to_bundled_25(fb25_server, fb25_database) -> None:
    """O mesmo .fdb que o FB 3.0 recusou abre normalmente no servidor
    bundled FB 2.5 — esse e o caminho de fallback que a Shift oferece."""
    config = {
        "host": fb25_server["host"],
        "port": fb25_server["port"],
        "database": fb25_database["container_path"],
        "username": "SYSDBA",
        "firebird_version": "2.5",
        "charset": "WIN1252",
    }
    conn = connect_firebird(config, {"password": "masterkey"})
    try:
        cur = conn.cursor()
        cur.execute("select 1 from rdb$database")
        row = cur.fetchone()
        assert row is not None and row[0] == 1
    finally:
        conn.close()


def test_c_auto_detect_picks_25_for_ods11(fb25_database) -> None:
    """Auto-deteccao do ODS 11 deve devolver '2.5' — base do roteamento
    automatico que evita o erro do test_c_fb4_rejects_ods11."""
    resolved = resolve_firebird_version_from_path(fb25_database["host_path"])
    assert resolved == "2.5", (
        f"auto-deteccao falhou para ODS 11: veio {resolved!r}"
    )
