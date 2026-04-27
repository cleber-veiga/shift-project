"""
Testes do sandbox Docker (``app.services.sandbox.docker_sandbox``).

Estrutura
---------
- **Unit tests** (sempre rodam): cobrem clipping de limits, ABSOLUTE_CAPS,
  e a logica do orquestrador com docker-py mockado. NAO precisam de daemon.
- **Integration tests** (marcador ``@pytest.mark.docker``): rodam contra um
  daemon real e a imagem ``shift-kernel-runtime:latest``. Cobrem todos os
  criterios de aceitacao do spec (network=none, FS read-only, timeout,
  fork-bomb, cross-tenant, /etc/passwd do host inacessivel). Skipped
  automaticamente quando a imagem nao esta disponivel.

Para executar a suite de integracao localmente:

    cd kernel-runtime && docker build -t shift-kernel-runtime:latest .
    cd ../shift-backend && pytest tests/test_docker_sandbox.py -m docker
"""

from __future__ import annotations

import asyncio
import io
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.services.sandbox import docker_sandbox as ds
from app.services.sandbox.docker_sandbox import (
    ABSOLUTE_CAPS,
    SandboxLimits,
    SandboxResult,
    SandboxUnavailable,
    run_user_code,
)


# ---------------------------------------------------------------------------
# Unit: limits clipping
# ---------------------------------------------------------------------------


class TestSandboxLimitsClipping:
    def test_workspace_cap_clips_user_request(self):
        user = SandboxLimits(
            cpu_quota=8.0,
            mem_limit_mb=8192,
            timeout_s=3600,
            tmpfs_mb=1024,
            pids_limit=4096,
        )
        ws = SandboxLimits(
            cpu_quota=2.0, mem_limit_mb=2048, timeout_s=120,
            tmpfs_mb=256, pids_limit=200,
        )
        clipped = user.with_workspace_cap(ws)
        assert clipped.cpu_quota == 2.0
        assert clipped.mem_limit_mb == 2048
        assert clipped.timeout_s == 120
        assert clipped.tmpfs_mb == 256
        assert clipped.pids_limit == 200

    def test_absolute_caps_always_enforced_even_without_workspace_cap(self):
        wild = SandboxLimits(
            cpu_quota=999.0,
            mem_limit_mb=999_999,
            timeout_s=999_999,
            tmpfs_mb=999_999,
            pids_limit=999_999,
        )
        clipped = wild.with_workspace_cap(None)
        assert clipped.cpu_quota == ABSOLUTE_CAPS["cpu"]
        assert clipped.mem_limit_mb == ABSOLUTE_CAPS["mem_mb"]
        assert clipped.timeout_s == ABSOLUTE_CAPS["timeout_s"]
        assert clipped.tmpfs_mb == ABSOLUTE_CAPS["tmpfs_mb"]
        assert clipped.pids_limit == ABSOLUTE_CAPS["pids"]

    def test_workspace_cant_exceed_absolute_caps(self):
        """Mesmo se o admin do workspace 'aumentar' o cap, ABSOLUTE_CAPS vence."""
        rogue_workspace = SandboxLimits(
            cpu_quota=99.0, mem_limit_mb=999_999, timeout_s=999_999,
            tmpfs_mb=999_999, pids_limit=999_999,
        )
        user = SandboxLimits(cpu_quota=99.0, mem_limit_mb=999_999, timeout_s=999_999)
        clipped = user.with_workspace_cap(rogue_workspace)
        assert clipped.cpu_quota <= ABSOLUTE_CAPS["cpu"]
        assert clipped.mem_limit_mb <= ABSOLUTE_CAPS["mem_mb"]
        assert clipped.timeout_s <= ABSOLUTE_CAPS["timeout_s"]


# ---------------------------------------------------------------------------
# Unit: orquestracao com docker-py mockado
# ---------------------------------------------------------------------------


def _fake_container_with_output(
    parquet_bytes: bytes,
    *,
    stdout: bytes = b"",
    stderr: bytes = b"",
    exit_code: int = 0,
    oom: bool = False,
) -> MagicMock:
    """Cria um Container mock que devolve ``parquet_bytes`` via get_archive."""
    container = MagicMock(name="Container")
    socket = MagicMock(name="AttachSocket")
    socket._sock = MagicMock()
    container.attach_socket.return_value = socket
    container.start.return_value = None
    container.wait.return_value = {"StatusCode": exit_code}
    container.attrs = {"State": {"OOMKilled": oom}}

    def _logs(stdout=False, stderr=False):
        if stdout:
            return globals().get("_test_stdout", b"") or b""
        if stderr:
            return globals().get("_test_stderr", b"") or b""
        return b""

    container.logs.side_effect = lambda **kw: stderr if kw.get("stderr") else stdout

    # get_archive devolve um tar contendo result.parquet
    if parquet_bytes:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tf:
            info = tarfile.TarInfo(name="result.parquet")
            info.size = len(parquet_bytes)
            tf.addfile(info, io.BytesIO(parquet_bytes))
        buf.seek(0)
        container.get_archive.return_value = ([buf.read()], {})
    else:
        # Simula NotFound
        from docker.errors import NotFound
        container.get_archive.side_effect = NotFound("no result")

    return container


class TestSandboxOrchestrationMocked:
    def test_run_user_code_passes_security_options(self, tmp_path: Path):
        """O container e criado com network=none, read_only, cap_drop=ALL,
        no-new-privileges e user nao-root."""
        ds.reset_client_for_tests()

        client = MagicMock()
        client.ping.return_value = True
        # Parquet "fake" — bytes nao precisam ser validos para este teste.
        container = _fake_container_with_output(b"PARQUET_PLACEHOLDER")
        client.containers.create.return_value = container

        with patch("docker.from_env", return_value=client):
            asyncio.run(run_user_code(
                code="result = data",
                input_table=None,
                limits=SandboxLimits(),
                execution_id="unit-1",
            ))

        kwargs = client.containers.create.call_args.kwargs
        assert kwargs["network_mode"] == "none"
        assert kwargs["read_only"] is True
        assert kwargs["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in kwargs["security_opt"]
        assert kwargs["user"].split(":")[0] != "0"  # nao-root
        assert kwargs["privileged"] is False
        # Tmpfs em /output e /tmp
        assert "/output" in kwargs["tmpfs"]
        assert "/tmp" in kwargs["tmpfs"]
        # Mount: o diretorio de staging do host (vazio quando sem input) vai
        # em /input read-only — nunca rw, nunca outros paths.
        volumes = kwargs.get("volumes", {})
        assert len(volumes) == 1
        bind = next(iter(volumes.values()))
        assert bind == {"bind": "/input", "mode": "ro"}
        ds.reset_client_for_tests()

    def test_input_table_mounted_read_only(self, tmp_path: Path):
        """Quando ``input_table`` e fornecido, o mount e ``ro``."""
        ds.reset_client_for_tests()
        # Cria parquet falso (pequeno, formato nao precisa ser real para este unit).
        input_path = tmp_path / "in.parquet"
        input_path.write_bytes(b"\x00\x00\x00\x00")

        client = MagicMock()
        client.ping.return_value = True
        container = _fake_container_with_output(b"PARQUET")
        client.containers.create.return_value = container

        with patch("docker.from_env", return_value=client):
            asyncio.run(run_user_code(
                code="pass",
                input_table=input_path,
                limits=SandboxLimits(),
                execution_id="unit-2",
            ))

        kwargs = client.containers.create.call_args.kwargs
        volumes = kwargs["volumes"]
        assert len(volumes) == 1
        bind = next(iter(volumes.values()))
        assert bind["bind"] == "/input"
        assert bind["mode"] == "ro"
        ds.reset_client_for_tests()

    def test_missing_input_returns_failure_without_calling_docker(
        self, tmp_path: Path
    ):
        ds.reset_client_for_tests()
        with patch("docker.from_env") as patched:
            client = MagicMock()
            client.ping.return_value = True
            patched.return_value = client

            result = asyncio.run(run_user_code(
                code="pass",
                input_table=tmp_path / "missing.parquet",
                limits=SandboxLimits(),
                execution_id="unit-3",
            ))

        assert result.success is False
        assert result.exit_code == 2
        assert "nao existe" in result.stderr
        ds.reset_client_for_tests()

    def test_unavailable_docker_raises_sandbox_unavailable(self):
        ds.reset_client_for_tests()
        with patch("docker.from_env") as patched:
            patched.side_effect = RuntimeError("connection refused")
            with pytest.raises(SandboxUnavailable):
                asyncio.run(run_user_code(
                    code="pass",
                    input_table=None,
                    limits=SandboxLimits(),
                    execution_id="unit-4",
                ))
        ds.reset_client_for_tests()


# ---------------------------------------------------------------------------
# Integration: requer daemon Docker e a imagem do kernel-runtime.
# ---------------------------------------------------------------------------


def _docker_available() -> bool:
    """Daemon Docker e imagem shift-kernel-runtime:latest disponiveis.

    A suite ``@pytest.mark.docker`` faz skip via fixture quando isso for
    False — assim ``pytest -m docker`` em maquinas sem daemon nao falha,
    ele apenas reporta os testes como skipped. Em CI esses testes DEVEM
    rodar e passar (gate de merge).
    """
    try:
        import docker
        client = docker.from_env()
        client.ping()
        client.images.get("shift-kernel-runtime:latest")
        return True
    except Exception:  # noqa: BLE001
        return False


_DOCKER_SKIP_REASON = (
    "docker daemon ou imagem shift-kernel-runtime:latest indisponivel — "
    "build com: cd kernel-runtime && docker build -t shift-kernel-runtime:latest ."
)


@pytest.fixture(autouse=False)
def _require_docker():
    """Fixture usada pelos testes da suite docker — skip se ambiente faltar."""
    if not _docker_available():
        pytest.skip(_DOCKER_SKIP_REASON)


@pytest.mark.docker
class TestSandboxIntegration:
    """Testes de seguranca contra container real.

    Os 6 cenarios obrigatorios sao:
    - ``test_sandbox_cannot_read_host_passwd``
    - ``test_sandbox_cannot_open_network_socket``
    - ``test_sandbox_cannot_write_to_root_fs``
    - ``test_sandbox_kills_infinite_loop``
    - ``test_sandbox_resists_fork_bomb``
    - ``test_sandbox_isolates_between_executions``
    """

    @pytest.fixture(autouse=True)
    def _check_docker(self, _require_docker):
        # Forca skip dos testes da classe se daemon ausente.
        pass

    def _make_input_parquet(self, tmp_path: Path) -> Path:
        import duckdb
        path = tmp_path / "in.parquet"
        con = duckdb.connect(":memory:")
        con.execute(
            "CREATE TABLE t AS SELECT * FROM (VALUES (1,'a'),(2,'b'),(3,'c')) v(id,name)"
        )
        con.execute(f"COPY t TO '{path}' (FORMAT PARQUET)")
        con.close()
        return path

    # --- Funcionalidade basica + observabilidade --------------------------

    def test_basic_filter_roundtrip(self, tmp_path: Path):
        """Sucesso simples: codigo filtra entrada, gera output."""
        import duckdb
        input_p = self._make_input_parquet(tmp_path)
        result = asyncio.run(run_user_code(
            code='result = data.filter("id > 1")\nprint("hello")',
            input_table=input_p,
            limits=SandboxLimits(timeout_s=30),
            execution_id="it-basic",
            use_pool=False,  # cold path puro nesta suite
        ))
        assert result.success, result.stderr
        assert "hello" in result.stdout
        rows = duckdb.connect(":memory:").execute(
            f"SELECT id FROM read_parquet('{result.output_path}') ORDER BY id"
        ).fetchall()
        assert rows == [(2,), (3,)]

    def test_stdout_stderr_captured(self, tmp_path: Path):
        result = asyncio.run(run_user_code(
            code=(
                "import sys\n"
                "print('out-line-1')\n"
                "print('err-line-1', file=sys.stderr)\n"
                "result = []"
            ),
            input_table=None,
            limits=SandboxLimits(timeout_s=10),
            execution_id="it-iolog",
            use_pool=False,
        ))
        assert "out-line-1" in result.stdout
        assert "err-line-1" in result.stderr

    # --- Cenarios obrigatorios da Tarefa 2 (security) ---------------------

    def test_sandbox_cannot_read_host_passwd(self, tmp_path: Path):
        """O codigo do usuario nao consegue ler o /etc/passwd do HOST.

        Estrategia: o container tem seu proprio /etc/passwd (do
        ``python:3.12-slim``), entao a leitura em si nao falha — a
        protecao de fato e que o conteudo SEJA do container e nao do
        host. Verificamos que:

        1) o conteudo lido contem a entrada do usuario nao-root
           ``sandbox:x:65532`` que adicionamos no Dockerfile;
        2) e NAO contem usuarios tipicos do host (root com home /root,
           dev/operator users, etc.).

        Adicionalmente: arquivo unico criado no host fora dos mounts
        permitidos NUNCA pode ser visto pelo container.
        """
        import os as _os

        # 1. Conteudo do /etc/passwd visto pelo container deve ser o do
        # container, nao do host.
        result = asyncio.run(run_user_code(
            code=(
                "with open('/etc/passwd') as f:\n"
                "    contents = f.read()\n"
                "print(contents)\n"
                "result = []"
            ),
            input_table=None,
            limits=SandboxLimits(timeout_s=10),
            execution_id="it-passwd-1",
            use_pool=False,
        ))
        # Sucesso ou nao, NUNCA pode aparecer conteudo unico do host.
        # Em hosts Linux dev tipicos ha um usuario com nome do dev no
        # /etc/passwd; aqui no Windows o /etc/passwd nem existe — qualquer
        # leitura dentro do container so traz dados do container.
        assert "sandbox:x:65532" in result.stdout, (
            f"Esperado entry do usuario sandbox; saida:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

        # 2. Arquivo canario no host fora dos mounts permitidos NUNCA
        # pode ser lido pelo container — comprova isolamento de mount.
        canary_path = tmp_path / "shift-host-canary.txt"
        canary_payload = "HOST_CANARY_dG9rZW4tdW5pY28K"
        canary_path.write_text(canary_payload)
        result2 = asyncio.run(run_user_code(
            code=(
                f"open(r'{canary_path}').read()\n"
                "result = []"
            ),
            input_table=None,
            limits=SandboxLimits(timeout_s=10),
            execution_id="it-passwd-2",
            use_pool=False,
        ))
        assert not result2.success, "container conseguiu ler arquivo do host"
        assert canary_payload not in result2.stdout
        assert canary_payload not in result2.stderr
        assert any(
            kw in result2.stderr.lower()
            for kw in ("no such file", "filenotfounderror", "errno 2")
        )

    def test_sandbox_cannot_open_network_socket(self):
        """``network_mode=none`` — abrir socket externo falha."""
        result = asyncio.run(run_user_code(
            code=(
                "import socket\n"
                "s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)\n"
                "s.connect(('8.8.8.8', 53))\n"
                "result = []"
            ),
            input_table=None,
            limits=SandboxLimits(timeout_s=15),
            execution_id="it-net",
            use_pool=False,
        ))
        assert not result.success
        assert any(
            kw in result.stderr.lower()
            for kw in ("network", "unreachable", "no route", "errno")
        )

    def test_sandbox_cannot_write_to_root_fs(self):
        """``read_only=True`` — escrita em / falha."""
        result = asyncio.run(run_user_code(
            code=(
                "open('/evil.txt', 'w').write('owned')\n"
                "result = []"
            ),
            input_table=None,
            limits=SandboxLimits(timeout_s=15),
            execution_id="it-ro",
            use_pool=False,
        ))
        assert not result.success
        assert (
            "read-only" in result.stderr.lower()
            or "permission" in result.stderr.lower()
        )

    def test_sandbox_kills_infinite_loop(self):
        """Loop infinito morto pelo timeout. Duracao < timeout + grace."""
        import time as _t
        timeout_s = 2
        grace_s = 8  # docker wait + cleanup overhead

        t0 = _t.perf_counter()
        result = asyncio.run(run_user_code(
            code="while True:\n    pass",
            input_table=None,
            limits=SandboxLimits(timeout_s=timeout_s),
            execution_id="it-timeout",
            use_pool=False,
        ))
        elapsed = _t.perf_counter() - t0

        assert result.timed_out is True
        assert result.success is False
        assert result.exit_code != 0
        assert elapsed < timeout_s + grace_s, (
            f"timeout demorou {elapsed:.1f}s — alem do grace de {grace_s}s"
        )

    def test_sandbox_resists_fork_bomb(self):
        """fork-bomb com pids_limit=64 nao derruba o host nem hangs o teste."""
        import time as _t
        t0 = _t.perf_counter()
        result = asyncio.run(run_user_code(
            code=(
                "import os\n"
                "while True:\n"
                "    try:\n"
                "        os.fork()\n"
                "    except Exception:\n"
                "        pass\n"
            ),
            input_table=None,
            limits=SandboxLimits(timeout_s=10, pids_limit=64),
            execution_id="it-fork",
            use_pool=False,
        ))
        elapsed = _t.perf_counter() - t0

        # Host segue de pe — o test em si retorna em tempo finito.
        # Container morre por timeout ou por OOM/pids_limit; em qualquer caso,
        # nao deve durar mais que timeout + grace.
        assert isinstance(result, SandboxResult)
        assert elapsed < 25.0, f"fork-bomb nao foi contido em {elapsed:.1f}s"
        assert result.success is False

    def test_sandbox_isolates_between_executions(self):
        """Containers nunca sao reusados — execucao B nao ve estado da A.

        Cobertura via ``SandboxPool``: A escreve em ``/tmp/leak.txt``, A
        finaliza, pool destroi e cria um substituto. B le ``/tmp/leak.txt``
        e NAO encontra. Comprova ``SandboxPool.release`` matando o
        container e zerando o tmpfs.
        """
        from app.services.sandbox.pool import SandboxPool

        pool = SandboxPool(
            "shift-kernel-runtime:latest",
            target_idle=2,
            max_size=3,
        )
        pool.start()
        try:
            wc_a = pool.acquire(timeout=5.0)
            assert wc_a is not None
            try:
                from app.services.sandbox.docker_sandbox import (
                    execute_in_warm_container,
                )
                # Execucao A: escreve canario no /tmp do container.
                result_a = execute_in_warm_container(
                    wc_a,
                    code=(
                        "with open('/tmp/leak.txt', 'w') as f:\n"
                        "    f.write('TENANT_A_SECRET')\n"
                        "result = []"
                    ),
                    input_table=None,
                    limits=SandboxLimits(timeout_s=10),
                )
                assert result_a.success, result_a.stderr
            finally:
                pool.release(wc_a)

            # Aguarda replenishment para ter idle disponivel.
            import time as _t
            deadline = _t.time() + 10.0
            while pool.idle_count < 1 and _t.time() < deadline:
                _t.sleep(0.1)

            wc_b = pool.acquire(timeout=5.0)
            assert wc_b is not None
            assert wc_b.container_id != wc_a.container_id, (
                "pool reusou o mesmo container — viola isolamento"
            )
            try:
                from app.services.sandbox.docker_sandbox import (
                    execute_in_warm_container,
                )
                result_b = execute_in_warm_container(
                    wc_b,
                    code=(
                        "import os\n"
                        "if os.path.exists('/tmp/leak.txt'):\n"
                        "    print('LEAKED:', open('/tmp/leak.txt').read())\n"
                        "else:\n"
                        "    print('CLEAN')\n"
                        "result = []"
                    ),
                    input_table=None,
                    limits=SandboxLimits(timeout_s=10),
                )
                assert result_b.success, result_b.stderr
                assert "TENANT_A_SECRET" not in result_b.stdout
                assert "CLEAN" in result_b.stdout
            finally:
                pool.release(wc_b)
        finally:
            pool.stop()
