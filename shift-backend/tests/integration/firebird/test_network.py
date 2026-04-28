"""
Testes de rede do container shift-backend — valida que host.docker.internal
resolve, garantindo que clientes com servidor Firebird no Windows host
consigam ser alcancados pelo backend (Cenario B).

Skip-if-not-running: se o stack nao esta up, o teste e ignorado com
mensagem clara em PT-BR.
"""

from __future__ import annotations

import shutil
import subprocess

import pytest


pytestmark = pytest.mark.firebird


def _docker_cli_available() -> bool:
    return shutil.which("docker") is not None


def _backend_container_running() -> bool:
    """Verifica se o service shift-backend esta de pe via 'docker compose ps'."""
    try:
        proc = subprocess.run(
            ["docker", "compose", "ps", "--status", "running", "--services"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    if proc.returncode != 0:
        return False
    services = {line.strip() for line in proc.stdout.splitlines() if line.strip()}
    return "shift-backend" in services


def test_host_docker_internal_resolves() -> None:
    """Dentro do container, 'getent hosts host.docker.internal' deve resolver.

    Garante que o extra_hosts: host-gateway esta ativo — caso contrario o
    backend nao alcanca servidores Firebird rodando no Windows host em
    ambientes Docker Engine (WSL2 / Linux nativo).
    """
    if not _docker_cli_available():
        pytest.skip("CLI 'docker' nao encontrada no PATH")
    if not _backend_container_running():
        pytest.skip(
            "Service 'shift-backend' nao esta rodando — suba o stack com "
            "'docker compose up -d shift-backend' antes de rodar este teste."
        )

    proc = subprocess.run(
        [
            "docker", "compose", "exec", "-T", "shift-backend",
            "getent", "hosts", "host.docker.internal",
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    assert proc.returncode == 0, (
        f"getent falhou (exit {proc.returncode}). stdout={proc.stdout!r} "
        f"stderr={proc.stderr!r}. Provavel causa: extra_hosts: host-gateway "
        "nao foi aplicado — recrie com 'docker compose up -d --force-recreate shift-backend'."
    )
    assert "host.docker.internal" in proc.stdout, (
        f"saida inesperada de getent: {proc.stdout!r}"
    )
