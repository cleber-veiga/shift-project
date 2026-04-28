"""
Cenario B — Firebird ja rodando no Windows host (acesso via host.docker.internal).

Estrategia: simular o host Windows com um container Firebird exposto em
porta efemera (fb30_server fixture). Backend conecta como se fosse remoto.
O ponto critico do cenario B e que o path do .fdb NAO deve ser traduzido —
o servidor remoto sabe interpretar 'C:\\...'.
"""

from __future__ import annotations

import shutil
import socket
import subprocess
from unittest.mock import patch

import pytest

from app.services.firebird_client import connect_firebird
from app.services.firebird_diagnostics import diagnose


pytestmark = pytest.mark.firebird


def test_b_path_preserved() -> None:
    """Com host nao-bundled, o path Windows literal deve chegar ao driver
    sem tradução para /firebird/data/...."""
    captured = {}

    def fake_connect(config, secret):
        captured["database"] = config.get("database")
        captured["host"] = config.get("host")
        return type("FakeConn", (), {"cursor": lambda self: None, "close": lambda self: None})()

    config = {
        "host": "127.0.0.1",
        "port": 3050,
        "database": r"C:\fake\path.fdb",
        "username": "SYSDBA",
        "firebird_version": "3+",
    }
    with patch(
        "app.services.firebird_client._connect_via_firebird_driver",
        side_effect=fake_connect,
    ):
        connect_firebird(config, {"password": "x"})

    assert captured["host"] == "127.0.0.1"
    assert captured["database"] == r"C:\fake\path.fdb", (
        f"path remoto NAO deveria ter sido traduzido: {captured['database']!r}"
    )


def test_b_diagnose_classifies_path_not_found(fb30_server) -> None:
    """Diagnose contra um servidor real, com path que nao existe nele.

    DNS/TCP/greeting passam (servidor responde); auth_query falha porque o
    arquivo nao existe no filesystem do servidor. Path Linux porque o
    container e Linux — path Windows arrisca disparar 'bad parameters on
    attach' (classifier mapearia para charset_mismatch). Classifier deve
    etiquetar como path_not_found.
    """
    steps = diagnose(
        host=fb30_server["host"],
        port=fb30_server["port"],
        database="/firebird/data/inexistente_shift_test.fdb",
        username="SYSDBA",
        password="masterkey",
        firebird_version="3+",
        timeout_per_step=3.0,
    )

    assert len(steps) == 4, [s["stage"] for s in steps]
    assert all(s["ok"] for s in steps[:3])
    auth = steps[3]
    assert auth["ok"] is False
    assert auth["error_class"] == "path_not_found", (
        f"esperado path_not_found, veio {auth['error_class']!r} (msg={auth['error_msg']!r})"
    )


def test_b_host_docker_internal_resolves() -> None:
    """De DENTRO do container shift-backend, getent hosts host.docker.internal
    deve resolver. Pula se o stack compose nao esta rodando."""
    if shutil.which("docker") is None:
        pytest.skip("CLI 'docker' nao encontrada — rodando fora de Docker")

    try:
        ps = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "--services"],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pytest.skip("docker compose nao disponivel")

    if "shift-backend" not in {l.strip() for l in ps.stdout.splitlines()}:
        pytest.skip(
            "Service 'shift-backend' nao esta rodando — suba com "
            "'docker compose up -d shift-backend' antes de rodar este teste."
        )

    proc = subprocess.run(
        ["docker", "compose", "exec", "-T", "shift-backend",
         "getent", "hosts", "host.docker.internal"],
        capture_output=True, text=True, timeout=15, check=False,
    )
    assert proc.returncode == 0, (
        f"host.docker.internal nao resolve dentro do backend (exit {proc.returncode}): "
        f"stderr={proc.stderr!r}"
    )
    assert "host.docker.internal" in proc.stdout
