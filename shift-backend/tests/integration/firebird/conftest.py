"""
Fixtures de integracao Firebird — sobe servidores 2.5 e 3.0 efemeros via
testcontainers e prepara bancos de teste acessiveis tanto pelo container
quanto pelo host (necessario para validar deteccao de ODS lendo o header
do .fdb diretamente).

Skip explicito quando Docker nao esta disponivel ou as imagens
``jacobalberty/firebird:2.5-ss`` / ``v3.0.10`` nao podem ser puxadas.
"""

from __future__ import annotations

import socket
import time
from pathlib import Path
from typing import Any

import pytest


_FB25_IMAGE = "jacobalberty/firebird:2.5-ss"
_FB30_IMAGE = "jacobalberty/firebird:v3.0.10"
_DB_FILENAME = "test.fdb"
_PASSWORD = "masterkey"
_CONTAINER_DATA_DIR = "/firebird/data"
_STARTUP_TIMEOUT_SECONDS = 60


def _docker_available() -> tuple[bool, str]:
    """Verifica se ha Docker daemon acessivel. Devolve (ok, motivo)."""
    try:
        import docker  # type: ignore[import-untyped]
    except ImportError:
        return False, "biblioteca 'docker' nao instalada (instale extras [dev])"

    try:
        client = docker.from_env()
        client.ping()
    except Exception as exc:  # noqa: BLE001
        return False, f"daemon Docker inacessivel: {exc}"
    return True, ""


def _testcontainers_available() -> tuple[bool, str]:
    try:
        import testcontainers.core.container  # noqa: F401
    except ImportError:
        return (
            False,
            "testcontainers-python nao instalado (rode 'pip install -e .[dev]')",
        )
    return True, ""


def _wait_port_open(host: str, port: int, timeout: float) -> bool:
    """Polla TCP ate aceitar conexao ou estourar timeout."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def _wait_db_file(path: Path, timeout: float) -> bool:
    """Polla o arquivo do banco aparecer no bind-mount com tamanho > 0."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and path.stat().st_size > 0:
            return True
        time.sleep(0.5)
    return False


def _start_firebird_container(
    image: str,
    host_data_dir: Path,
    extra_env: dict[str, str] | None = None,
) -> Any:
    """Sobe um container Firebird com bind-mount em /firebird/data e
    FIREBIRD_DATABASE=test.fdb. Devolve o objeto container ja iniciado."""
    from testcontainers.core.container import DockerContainer

    host_data_dir.mkdir(parents=True, exist_ok=True)

    container = (
        DockerContainer(image)
        .with_env("ISC_PASSWORD", _PASSWORD)
        .with_env("FIREBIRD_DATABASE", _DB_FILENAME)
        .with_exposed_ports(3050)
        .with_volume_mapping(str(host_data_dir), _CONTAINER_DATA_DIR, "rw")
    )
    if extra_env:
        for key, value in extra_env.items():
            container = container.with_env(key, value)

    container.start()
    return container


# ---------------------------------------------------------------------------
# Fixtures de servidor (scope=session — reaproveita entre testes)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _docker_guard() -> None:
    ok_tc, why_tc = _testcontainers_available()
    if not ok_tc:
        pytest.skip(f"Suite Firebird ignorada: {why_tc}", allow_module_level=False)
    ok_dk, why_dk = _docker_available()
    if not ok_dk:
        pytest.skip(f"Suite Firebird ignorada: {why_dk}", allow_module_level=False)


@pytest.fixture(scope="session")
def fb25_server(_docker_guard, tmp_path_factory) -> Any:
    """Sobe Firebird 2.5 em porta efemera. Bind-monta um tmp dir do host
    em /firebird/data para que o .fdb auto-criado fique legivel pelo host."""
    host_dir = tmp_path_factory.mktemp("fb25-data")
    container = _start_firebird_container(
        _FB25_IMAGE,
        host_dir,
        extra_env={"EnableLegacyClientAuth": "true"},
    )
    try:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(3050))
        if not _wait_port_open(host, port, _STARTUP_TIMEOUT_SECONDS):
            pytest.skip(f"Firebird 2.5 nao subiu em {_STARTUP_TIMEOUT_SECONDS}s")
        yield {
            "host": host,
            "port": port,
            "host_data_dir": host_dir,
            "container": container,
        }
    finally:
        try:
            container.stop()
        except Exception:  # noqa: BLE001
            pass


@pytest.fixture(scope="session")
def fb30_server(_docker_guard, tmp_path_factory) -> Any:
    """Sobe Firebird 3.0 em porta efemera (analogo ao fb25_server)."""
    host_dir = tmp_path_factory.mktemp("fb30-data")
    container = _start_firebird_container(_FB30_IMAGE, host_dir)
    try:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(3050))
        if not _wait_port_open(host, port, _STARTUP_TIMEOUT_SECONDS):
            pytest.skip(f"Firebird 3.0 nao subiu em {_STARTUP_TIMEOUT_SECONDS}s")
        yield {
            "host": host,
            "port": port,
            "host_data_dir": host_dir,
            "container": container,
        }
    finally:
        try:
            container.stop()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Fixtures de banco — caminho do .fdb dentro do container e no host
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def fb25_database(fb25_server) -> dict[str, Any]:
    """Caminhos do .fdb auto-criado pelo container FB 2.5."""
    host_path = Path(fb25_server["host_data_dir"]) / _DB_FILENAME
    if not _wait_db_file(host_path, _STARTUP_TIMEOUT_SECONDS):
        pytest.skip(
            f"Banco {_DB_FILENAME} nao apareceu no bind-mount do FB 2.5 "
            "(possivel problema de permissao no host)"
        )
    return {
        "host_path": str(host_path),
        "container_path": f"{_CONTAINER_DATA_DIR}/{_DB_FILENAME}",
    }


@pytest.fixture(scope="session")
def fb30_database(fb30_server) -> dict[str, Any]:
    """Caminhos do .fdb auto-criado pelo container FB 3.0."""
    host_path = Path(fb30_server["host_data_dir"]) / _DB_FILENAME
    if not _wait_db_file(host_path, _STARTUP_TIMEOUT_SECONDS):
        pytest.skip(
            f"Banco {_DB_FILENAME} nao apareceu no bind-mount do FB 3.0 "
            "(possivel problema de permissao no host)"
        )
    return {
        "host_path": str(host_path),
        "container_path": f"{_CONTAINER_DATA_DIR}/{_DB_FILENAME}",
    }


@pytest.fixture(scope="session")
def fb25_db_in_fb30_mount(fb25_database, fb30_server) -> dict[str, Any]:
    """Copia o .fdb ODS 11 (criado pelo FB 2.5) para o bind-mount do FB 3.0.

    Usado pelo cenario C: o FB 3.0+ tenta atachar um arquivo ODS 11.x e
    rejeita com 'unsupported on-disk structure'.
    """
    import shutil

    src = Path(fb25_database["host_path"])
    dst_dir = Path(fb30_server["host_data_dir"])
    dst = dst_dir / "ods11_in_fb30.fdb"
    if not dst.exists():
        shutil.copy2(src, dst)
    return {
        "host_path": str(dst),
        "container_path": f"{_CONTAINER_DATA_DIR}/ods11_in_fb30.fdb",
    }
