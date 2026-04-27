"""Sandbox Docker para execucao isolada de codigo de usuario.

Adapted from Flowfile project, MIT License — ver kernel-runtime/LICENSE
e kernel-runtime/NOTICE no monorepo.

Diferente da arquitetura original do Flowfile (kernel persistente FastAPI
multi-tenant), este modulo lanca um container *efemero* por execucao:
um codigo, um container. A vida util do container e exatamente a vida util
da execucao do node — apos o exit, nada sobrevive.

Garantias de seguranca aplicadas em todos os caminhos
-----------------------------------------------------
- ``network_mode="none"`` — container nao alcanca a rede.
- ``read_only=True`` — rootfs read-only; usuario nao consegue escrever
  fora dos diretorios tmpfs explicitos.
- ``tmpfs={"/tmp": ..., "/output": ...}`` — escrita confinada a tmpfs
  bound a memoria do container, com ``size`` cap.
- ``cap_drop=["ALL"]`` — nenhuma capability Linux.
- ``security_opt=["no-new-privileges:true"]`` — bloqueia setuid escalation.
- ``user="65532:65532"`` — usuario nao-root (mesmo do Dockerfile).
- ``pids_limit=128`` — fork-bomb killed pelo kernel.
- ``mem_limit`` / ``nano_cpus`` / ``timeout_s`` — caps duros.
- Mount do input em ``/input`` e ``read_only=True``; nenhum outro mount
  do host e permitido. Nada de docker.sock, sem ``-v`` arbitrario.

Caps absolutos por workspace
----------------------------
``SandboxLimits.with_workspace_cap(...)`` clipa os limits do usuario nos
caps do workspace, e estes nos caps absolutos da plataforma. Isso garante
que mesmo se um workspace admin configurar ``mem_limit_mb=999_999``, a
execucao nao passa do hard cap global definido em settings.

Pre-requisitos
--------------
- ``docker`` Python SDK (``pip install docker``).
- Daemon Docker acessivel via ``DOCKER_HOST`` ou socket padrao.
- Imagem ``SANDBOX_IMAGE`` ja construida (``cd kernel-runtime && docker build``).
"""

from __future__ import annotations

import asyncio
import io
import logging
import shutil
import tarfile
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator, Optional
from uuid import uuid4


logger = logging.getLogger(__name__)


if TYPE_CHECKING:  # pragma: no cover — types-only
    from docker import DockerClient
    from docker.models.containers import Container


# ---------------------------------------------------------------------------
# Config / cap absoluto
# ---------------------------------------------------------------------------


# Cap *absoluto* da plataforma. Nao e configuravel por workspace — e o
# limite alem do qual nenhum tenant pode ir, mesmo que a config local
# diga o contrario. Documentado em produto: "execucao limitada a 4 CPUs,
# 4GB RAM, 10min".
ABSOLUTE_CAPS = {
    "cpu": 4.0,        # 4 CPUs
    "mem_mb": 4096,    # 4GB
    "timeout_s": 600,  # 10min
    "tmpfs_mb": 512,   # 512MB no tmpfs do output
    "pids": 256,       # 256 processos / threads
}


@dataclass(frozen=True)
class SandboxLimits:
    """Limites aplicados ao container do usuario.

    Os valores default sao razoaveis para code_node tipico — 1 CPU, 512MB,
    60s. Workspace admins podem aumentar via config, mas nunca alem dos
    ``ABSOLUTE_CAPS`` (clipped por ``with_workspace_cap``).
    """

    cpu_quota: float = 1.0           # numero de CPUs (1.0 = uma CPU full)
    mem_limit_mb: int = 512
    timeout_s: int = 60
    tmpfs_mb: int = 128              # tamanho do /output e /tmp
    pids_limit: int = 128

    def with_workspace_cap(
        self,
        workspace_cap: "SandboxLimits | None" = None,
    ) -> "SandboxLimits":
        """Devolve um novo ``SandboxLimits`` com cada campo clippado em
        ``min(self, workspace_cap, ABSOLUTE_CAPS)``."""
        ws = workspace_cap or _ABSOLUTE_CAP_LIMITS
        return SandboxLimits(
            cpu_quota=min(self.cpu_quota, ws.cpu_quota, ABSOLUTE_CAPS["cpu"]),
            mem_limit_mb=min(self.mem_limit_mb, ws.mem_limit_mb, ABSOLUTE_CAPS["mem_mb"]),
            timeout_s=min(self.timeout_s, ws.timeout_s, ABSOLUTE_CAPS["timeout_s"]),
            tmpfs_mb=min(self.tmpfs_mb, ws.tmpfs_mb, ABSOLUTE_CAPS["tmpfs_mb"]),
            pids_limit=min(self.pids_limit, ws.pids_limit, ABSOLUTE_CAPS["pids"]),
        )


_ABSOLUTE_CAP_LIMITS = SandboxLimits(
    cpu_quota=ABSOLUTE_CAPS["cpu"],
    mem_limit_mb=ABSOLUTE_CAPS["mem_mb"],
    timeout_s=ABSOLUTE_CAPS["timeout_s"],
    tmpfs_mb=ABSOLUTE_CAPS["tmpfs_mb"],
    pids_limit=ABSOLUTE_CAPS["pids"],
)


@dataclass
class SandboxResult:
    """Outcome de uma execucao no sandbox."""

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    output_path: Path | None
    duration_s: float
    timed_out: bool = False
    oom_killed: bool = False
    error: str | None = None


class SandboxTimeout(RuntimeError):
    """Levantado quando o container nao termina antes de ``timeout_s``."""


class SandboxUnavailable(RuntimeError):
    """Daemon Docker nao acessivel ou imagem ausente."""


# ---------------------------------------------------------------------------
# Cliente docker — lazy import para nao quebrar quando docker nao esta
# instalado em ambientes que so usam o code_node legacy in-process.
# ---------------------------------------------------------------------------


_client_lock = threading.Lock()
_client: "DockerClient | None" = None


def _get_docker_client() -> "DockerClient":
    global _client
    with _client_lock:
        if _client is not None:
            return _client
        try:
            import docker  # local import: dep opcional
            _client = docker.from_env()
            # Ping para garantir daemon acessivel — sem isso, run_user_code
            # falha so na primeira chamada com erro confuso.
            _client.ping()
            return _client
        except Exception as exc:  # noqa: BLE001
            raise SandboxUnavailable(
                f"Docker indisponivel: {type(exc).__name__}: {exc}"
            ) from exc


def reset_client_for_tests() -> None:
    """Reseta o singleton — usado pelos tests para forcar re-conexao."""
    global _client
    with _client_lock:
        _client = None


# ---------------------------------------------------------------------------
# WarmContainer + helpers reutilizados pelo pool
# ---------------------------------------------------------------------------


@dataclass
class WarmContainer:
    """Container ja criado, iniciado e com socket de stdin atado.

    Pode estar em dois estados:
    - **idle**: o runner do kernel esta bloqueado em ``sys.stdin.read()``
      esperando o codigo. ``acquire`` do pool retorna nesse estado.
    - **in-use**: caller acabou de escrever o codigo no socket. Apos o
      runner terminar, o container e descartado (destroy).
    """

    container: Any  # docker.models.containers.Container
    socket: Any
    image: str
    host_workdir: Path
    host_input_dir: Path
    created_at: float = field(default_factory=time.time)

    @property
    def container_id(self) -> str:
        try:
            return self.container.id  # type: ignore[no-any-return]
        except Exception:  # noqa: BLE001
            return "<unknown>"


def _security_kwargs(
    limits: SandboxLimits,
    *,
    host_input_dir: Path,
) -> dict[str, Any]:
    """Args do ``containers.create`` aplicando todas as restricoes do spec.

    Compartilhado pelo cold path e pelo pool — garante que QUALQUER
    container do sandbox tenha as mesmas garantias de isolamento.
    """
    nano_cpus = int(limits.cpu_quota * 1_000_000_000)
    tmpfs_size = f"{limits.tmpfs_mb}m"
    return dict(
        stdin_open=True,
        hostname="sandbox",
        network_mode="none",
        read_only=True,
        tmpfs={
            "/tmp": f"size={tmpfs_size},mode=1777",
            "/output": f"size={tmpfs_size},mode=1777,uid=65532,gid=65532",
        },
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        user="65532:65532",
        pids_limit=limits.pids_limit,
        mem_limit=f"{limits.mem_limit_mb}m",
        memswap_limit=f"{limits.mem_limit_mb}m",
        nano_cpus=nano_cpus,
        auto_remove=False,
        privileged=False,
        volumes={
            str(host_input_dir): {"bind": "/input", "mode": "ro"},
        },
    )


def create_warm_container(
    image: str,
    limits: SandboxLimits,
    *,
    name_hint: str | None = None,
) -> WarmContainer:
    """Cria + inicia um container e devolve sua handle warm.

    Cada container tem seu PROPRIO ``host_input_dir`` em
    ``/tmp/shift/sandbox-pool/<id>/input/`` — bind mount em /input ro.
    Entre execucoes nao ha overlap: o pool destroi o container e remove
    o workdir antes de criar o substituto.

    O socket de stdin e atado e retornado dentro de ``WarmContainer``;
    o runner do kernel esta bloqueado em ``sys.stdin.read()`` esperando
    o codigo do usuario.
    """
    client = _get_docker_client()

    cid_hint = name_hint or uuid4().hex[:12]
    workdir = (
        Path(tempfile.gettempdir())
        / "shift"
        / "sandbox-pool"
        / cid_hint
    )
    input_dir = workdir / "input"
    workdir.mkdir(parents=True, exist_ok=True)
    input_dir.mkdir(parents=True, exist_ok=True)

    kwargs = _security_kwargs(limits, host_input_dir=input_dir)
    container = client.containers.create(
        image=image,
        name=f"shift-sandbox-{cid_hint}",
        **kwargs,
    )
    socket = container.attach_socket(params={"stdin": 1, "stream": 1})
    container.start()

    return WarmContainer(
        container=container,
        socket=socket,
        image=image,
        host_workdir=workdir,
        host_input_dir=input_dir,
    )


def execute_in_warm_container(
    wc: WarmContainer,
    code: str,
    *,
    input_table: Path | None,
    limits: SandboxLimits,
) -> SandboxResult:
    """Faz a execucao em um container ja preparado (warm ou cold one-shot).

    Mantem todo o protocolo do cold path: stage do input no workdir do
    container, write do codigo no socket, wait com timeout, extract do
    output, leitura de stdout/stderr. NAO destroi o container — o caller
    decide (cold path: destroy imediato; pool: release destroi e
    repoe).
    """
    started = time.perf_counter()

    # Stage do input — escreve dentro do host_input_dir do container.
    # Cada warm container tem seu proprio dir; nao ha colisao entre
    # tenants paralelos.
    if input_table is not None:
        if not input_table.exists():
            return SandboxResult(
                success=False,
                exit_code=2,
                stdout="",
                stderr=f"input_table {input_table} nao existe",
                output_path=None,
                duration_s=time.perf_counter() - started,
                error="input_table_missing",
            )
        shutil.copy2(input_table, wc.host_input_dir / "table.parquet")

    container = wc.container
    socket = wc.socket

    try:
        payload = code.encode("utf-8")
        if hasattr(socket, "_sock"):
            socket._sock.sendall(payload)
            try:
                socket._sock.shutdown(1)  # SHUT_WR — fecha stdin
            except OSError:
                pass
        else:  # pragma: no cover — fallback
            socket.write(payload)  # type: ignore[attr-defined]
    finally:
        try:
            socket.close()
        except Exception:  # noqa: BLE001
            pass

    timed_out = False
    try:
        wait_result = container.wait(timeout=limits.timeout_s)
        exit_code = int(wait_result.get("StatusCode", -1))
    except Exception as exc:  # noqa: BLE001 — typically ReadTimeout
        return SandboxResult(
            success=False,
            exit_code=124,
            stdout="",
            stderr=f"timeout apos {limits.timeout_s}s: {exc}",
            output_path=None,
            duration_s=time.perf_counter() - started,
            timed_out=True,
            error="timeout",
        )

    container.reload()
    state = container.attrs.get("State", {})
    oom = bool(state.get("OOMKilled"))

    stdout_b = container.logs(stdout=True, stderr=False) or b""
    stderr_b = container.logs(stdout=False, stderr=True) or b""

    output_path: Optional[Path] = None
    if exit_code == 0:
        output_path = _extract_output_parquet(container, wc.host_workdir / "out")
        if output_path is not None:
            persistent = (
                Path(tempfile.gettempdir())
                / "shift"
                / "sandbox-results"
                / uuid4().hex
            )
            persistent.mkdir(parents=True, exist_ok=True)
            final = persistent / "result.parquet"
            shutil.move(str(output_path), str(final))
            output_path = final

    return SandboxResult(
        success=exit_code == 0 and not oom and not timed_out,
        exit_code=exit_code,
        stdout=stdout_b.decode("utf-8", errors="replace"),
        stderr=stderr_b.decode("utf-8", errors="replace"),
        output_path=output_path,
        duration_s=time.perf_counter() - started,
        timed_out=timed_out,
        oom_killed=oom,
        error=None if exit_code == 0 else f"exit_code={exit_code}",
    )


def destroy_warm_container(wc: WarmContainer) -> None:
    """Mata, remove e limpa workdir do host. Idempotente, swallow errors."""
    _safe_remove(wc.container)
    try:
        shutil.rmtree(wc.host_workdir, ignore_errors=True)
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------------------
# Helpers internos — extracao de output via tarball
# ---------------------------------------------------------------------------


def _extract_output_parquet(container: "Container", host_dir: Path) -> Path | None:
    """Le ``/output/result.parquet`` do container via ``get_archive`` e
    grava em ``host_dir``. Retorna ``None`` se o arquivo nao existe (ex.
    codigo do usuario falhou antes de gravar)."""
    try:
        bits, _stat = container.get_archive("/output/result.parquet")
    except Exception:  # noqa: BLE001 — arquivo nao existe (NotFound) etc.
        return None

    raw = io.BytesIO()
    for chunk in bits:
        raw.write(chunk)
    raw.seek(0)

    with tarfile.open(fileobj=raw, mode="r") as tf:
        member = tf.next()
        if member is None or not member.isfile():
            return None
        host_dir.mkdir(parents=True, exist_ok=True)
        out_path = host_dir / "result.parquet"
        extracted = tf.extractfile(member)
        if extracted is None:
            return None
        with out_path.open("wb") as fh:
            shutil.copyfileobj(extracted, fh)
        return out_path


def _safe_remove(container: "Container") -> None:
    """Mata e remove o container; engole erros de cleanup."""
    try:
        container.kill()
    except Exception:  # noqa: BLE001 — ja morreu, ja foi removido, etc.
        pass
    try:
        container.remove(force=True)
    except Exception:  # noqa: BLE001
        pass


@contextmanager
def _sandbox_workdir(execution_id: str | None = None) -> Iterator[Path]:
    """Cria um diretorio temporario do host para staging do input/output.

    Seu papel e isolar o input desta execucao de qualquer outra. O caller
    nao escreve nele depois do mount; o container so le. Removido no
    ``__exit__`` independente de sucesso/falha.
    """
    eid = execution_id or uuid4().hex
    base = Path(tempfile.gettempdir()) / "shift" / "sandbox" / eid
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        try:
            shutil.rmtree(base, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# API publica
# ---------------------------------------------------------------------------


async def run_user_code(
    code: str,
    *,
    input_table: Path | None = None,
    limits: SandboxLimits | None = None,
    image: str | None = None,
    execution_id: str | None = None,
    use_pool: bool = True,
) -> SandboxResult:
    """Executa ``code`` em um container Docker isolado e retorna o resultado.

    Parametros
    ----------
    code:
        Fonte Python que sera passada para STDIN do container. Veja
        ``kernel-runtime/kernel/runner.py`` para o protocolo.
    input_table:
        Path *no host* para um arquivo parquet que sera montado como
        ``/input/table.parquet`` (read-only). Quando ``None``, o codigo
        do usuario roda sem entrada.
    limits:
        ``SandboxLimits`` ja clipped pelos caps do workspace + plataforma.
        Se omitido, usa os defaults do dataclass.
    image:
        Override da imagem (default: settings ``SANDBOX_IMAGE``).
    execution_id:
        Tag do tmpdir do host e do nome do container — facilita debug e
        observabilidade.
    """
    from app.core.config import settings

    effective = (limits or SandboxLimits()).with_workspace_cap(_ABSOLUTE_CAP_LIMITS)
    image = image or getattr(settings, "SANDBOX_IMAGE", "shift-kernel-runtime:latest")

    return await asyncio.to_thread(
        _run_user_code_sync,
        code,
        input_table,
        effective,
        image,
        execution_id,
        use_pool,
    )


def _limits_match_default(limits: SandboxLimits) -> bool:
    """Indica se ``limits`` corresponde aos defaults do ``SandboxPool``.

    Pool so estoca containers warm com defaults. Custom = cold path.
    """
    from app.core.config import settings as _settings

    return (
        limits.cpu_quota == _settings.SANDBOX_DEFAULT_CPU_QUOTA
        and limits.mem_limit_mb == _settings.SANDBOX_DEFAULT_MEM_LIMIT_MB
        and limits.timeout_s == _settings.SANDBOX_DEFAULT_TIMEOUT_S
        and limits.tmpfs_mb == _settings.SANDBOX_DEFAULT_TMPFS_MB
        and limits.pids_limit == _settings.SANDBOX_DEFAULT_PIDS_LIMIT
    )


def _run_user_code_sync(
    code: str,
    input_table: Path | None,
    limits: SandboxLimits,
    image: str,
    execution_id: str | None,
    use_pool: bool,
) -> SandboxResult:
    """Implementacao sync — caminho warm (via pool) ou cold (one-shot)."""
    started = time.perf_counter()

    # Caminho warm: tenta acquire do pool quando disponivel e os limits
    # batem com os defaults. Em qualquer outro caso, cold one-shot.
    if use_pool and _limits_match_default(limits):
        try:
            from app.services.sandbox.pool import get_pool
            pool = get_pool(image)
        except Exception:  # noqa: BLE001 — pool nao instanciado, cold fallback
            pool = None
        if pool is not None:
            wc = pool.acquire(timeout=2.0)
            if wc is not None:
                try:
                    return execute_in_warm_container(
                        wc, code, input_table=input_table, limits=limits,
                    )
                finally:
                    pool.release(wc)

    # Cold one-shot: cria + usa + destroi.
    try:
        wc = create_warm_container(image, limits, name_hint=execution_id)
    except SandboxUnavailable:
        # Daemon ausente — sinaliza upstream (caller decide como tratar).
        # E erro de infra, nao de codigo do usuario.
        raise
    except Exception as exc:  # noqa: BLE001
        return SandboxResult(
            success=False,
            exit_code=2,
            stdout="",
            stderr=str(exc),
            output_path=None,
            duration_s=time.perf_counter() - started,
            error=f"create_failed: {type(exc).__name__}",
        )
    try:
        return execute_in_warm_container(
            wc, code, input_table=input_table, limits=limits,
        )
    finally:
        destroy_warm_container(wc)
