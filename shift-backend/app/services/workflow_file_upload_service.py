"""
Servico de upload de arquivos para nos e variaveis de workflow.

Armazena arquivos em disco local (``WORKFLOW_UPLOAD_DIR``) e indexa os
metadados em um JSON por workflow. Em producao substitua por bucket
S3/MinIO alterando apenas este modulo — toda a integracao com nos
acontece via ``resolve_url()``, que pode passar a devolver um path
local baixado on-demand a partir do bucket.

URI scheme suportado pelos nos: ``shift-upload://<file_id>``. Esse
scheme desacopla a definicao do workflow da localizacao fisica do
arquivo, sobrevivendo a migracao de storage.

Arquivos no indice tem os campos:
    - original_filename : nome original do upload
    - path              : path absoluto no disco
    - size_bytes        : tamanho do arquivo em bytes
    - sha256            : hash do conteudo (usado pra dedup)
    - created_at        : ISO 8601 UTC, set no save inicial
    - last_accessed_at  : ISO 8601 UTC, atualizado a cada touch()

Dedup: ``save()`` calcula sha256 do conteudo. Se ja existe outro upload
do mesmo workflow com o mesmo hash, retorna o file_id existente sem
gravar uma copia. Reduz storage em casos de re-upload do mesmo CSV.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkflowFileUploadService:
    """Gerencia o ciclo de vida de arquivos uploadados para workflows."""

    # ------------------------------------------------------------------
    # Helpers de filesystem
    # ------------------------------------------------------------------

    def _root_dir(self) -> Path:
        return Path(settings.WORKFLOW_UPLOAD_DIR)

    def _workflow_dir(self, workflow_id: str) -> Path:
        path = self._root_dir() / workflow_id
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _index_path(self, workflow_id: str) -> Path:
        return self._workflow_dir(workflow_id) / "_index.json"

    def _load_index(self, workflow_id: str) -> dict[str, dict[str, Any]]:
        path = self._index_path(workflow_id)
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}

    def _save_index(self, workflow_id: str, index: dict[str, dict[str, Any]]) -> None:
        self._index_path(workflow_id).write_text(
            json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------
    # API publica
    # ------------------------------------------------------------------

    def save(
        self,
        workflow_id: str,
        filename: str,
        content: bytes,
    ) -> dict[str, Any]:
        """Persiste o arquivo e retorna metadados.

        Faz dedup por sha256 dentro do mesmo workflow — se o usuario
        re-envia o mesmo arquivo, retorna o file_id existente sem
        regravar. Sempre atualiza ``last_accessed_at`` (re-upload e
        sinal de uso).

        Returns:
            dict com chaves: file_id, url (path absoluto), size_bytes,
            original_filename, sha256, deduped (bool).
        """
        sha256 = hashlib.sha256(content).hexdigest()
        size_bytes = len(content)
        index = self._load_index(workflow_id)

        # Dedup: existe upload com mesmo hash neste workflow?
        for fid, meta in index.items():
            if meta.get("sha256") == sha256 and Path(meta.get("path", "")).exists():
                meta["last_accessed_at"] = _utcnow_iso()
                self._save_index(workflow_id, index)
                return {
                    "file_id": fid,
                    "url": meta["path"],
                    "size_bytes": meta.get("size_bytes", size_bytes),
                    "original_filename": meta.get("original_filename", filename),
                    "sha256": sha256,
                    "deduped": True,
                }

        # Cria novo
        suffix = Path(filename).suffix.lower()
        file_id = str(uuid.uuid4())
        dest = self._workflow_dir(workflow_id) / f"{file_id}{suffix}"
        dest.write_bytes(content)

        now = _utcnow_iso()
        index[file_id] = {
            "original_filename": filename,
            "path": str(dest.resolve()),
            "size_bytes": size_bytes,
            "sha256": sha256,
            "created_at": now,
            "last_accessed_at": now,
        }
        self._save_index(workflow_id, index)
        return {
            "file_id": file_id,
            "url": str(dest.resolve()),
            "size_bytes": size_bytes,
            "original_filename": filename,
            "sha256": sha256,
            "deduped": False,
        }

    def resolve_url(self, workflow_id: str, file_id: str) -> str | None:
        """Resolve file_id para o path absoluto. None se nao existir."""
        index = self._load_index(workflow_id)
        entry = index.get(file_id)
        if entry is None:
            return None
        path = entry.get("path", "")
        if not Path(path).exists():
            return None
        return path

    def touch(self, workflow_id: str, file_id: str) -> None:
        """Atualiza last_accessed_at do arquivo. Idempotente, silencioso
        se file_id nao existir (caller ja teria pego no resolve_url)."""
        index = self._load_index(workflow_id)
        entry = index.get(file_id)
        if entry is None:
            return
        entry["last_accessed_at"] = _utcnow_iso()
        self._save_index(workflow_id, index)

    def list_files(self, workflow_id: str) -> list[dict[str, Any]]:
        """Lista todos os arquivos do workflow com seus metadados."""
        index = self._load_index(workflow_id)
        return [
            {"file_id": fid, **meta}
            for fid, meta in index.items()
        ]

    def delete(self, workflow_id: str, file_id: str) -> bool:
        """Remove arquivo manualmente. Retorna True se removeu, False se
        file_id nao existia."""
        index = self._load_index(workflow_id)
        entry = index.pop(file_id, None)
        if entry is None:
            return False
        path = Path(entry.get("path", ""))
        if path.exists():
            try:
                path.unlink()
            except Exception:  # noqa: BLE001
                logger.warning(
                    "upload.delete.unlink_failed",
                    workflow_id=workflow_id,
                    file_id=file_id,
                    path=str(path),
                )
        self._save_index(workflow_id, index)
        return True

    # ------------------------------------------------------------------
    # Quota & cleanup (uso por endpoints e jobs)
    # ------------------------------------------------------------------

    def get_quota_used_for_workflows(self, workflow_ids: list[str]) -> int:
        """Soma size_bytes de todos arquivos dos workflows fornecidos.

        Caller passa a lista de workflow_ids do projeto (resolvidos via
        DB pelo endpoint). Service nao acessa DB — fica desacoplado.
        """
        total = 0
        for wid in workflow_ids:
            index = self._load_index(wid)
            for meta in index.values():
                total += int(meta.get("size_bytes", 0))
        return total

    def cleanup_expired(self, ttl_days: int) -> dict[str, int]:
        """Remove arquivos com last_accessed_at < now - ttl_days.

        Itera todos os subdiretorios do WORKFLOW_UPLOAD_DIR (cada um
        e um workflow_id). Retorna {removed_files, freed_bytes}.
        """
        if ttl_days <= 0:
            return {"removed_files": 0, "freed_bytes": 0}

        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - (ttl_days * 86400)

        removed_files = 0
        freed_bytes = 0

        root = self._root_dir()
        if not root.exists():
            return {"removed_files": 0, "freed_bytes": 0}

        for workflow_dir in root.iterdir():
            if not workflow_dir.is_dir():
                continue
            workflow_id = workflow_dir.name
            index = self._load_index(workflow_id)
            mutated = False
            for fid in list(index.keys()):
                entry = index[fid]
                last_access = entry.get("last_accessed_at") or entry.get("created_at")
                if not last_access:
                    # Sem timestamp — usa mtime do arquivo como fallback.
                    path = Path(entry.get("path", ""))
                    if not path.exists():
                        index.pop(fid)
                        mutated = True
                        continue
                    last_ts = path.stat().st_mtime
                else:
                    try:
                        last_ts = datetime.fromisoformat(last_access).timestamp()
                    except ValueError:
                        # Timestamp corrompido — apaga conservadoramente
                        last_ts = 0

                if last_ts < cutoff:
                    path = Path(entry.get("path", ""))
                    size = int(entry.get("size_bytes", 0))
                    if path.exists():
                        try:
                            path.unlink()
                        except Exception:  # noqa: BLE001
                            logger.warning(
                                "upload.cleanup.unlink_failed",
                                workflow_id=workflow_id,
                                file_id=fid,
                                path=str(path),
                            )
                            continue
                    index.pop(fid)
                    removed_files += 1
                    freed_bytes += size
                    mutated = True

            if mutated:
                self._save_index(workflow_id, index)

        return {"removed_files": removed_files, "freed_bytes": freed_bytes}


workflow_file_upload_service = WorkflowFileUploadService()
