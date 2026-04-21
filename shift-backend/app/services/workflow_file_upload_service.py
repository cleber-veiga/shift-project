"""
Servico de upload de arquivos para variaveis do tipo file_upload.

Armazena arquivos em disco local (WORKFLOW_UPLOAD_DIR) e indexa
os metadados em um JSON por workflow. Em producao substitua por
bucket S3/MinIO alterando apenas este modulo.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings


class WorkflowFileUploadService:
    """Gerencia o ciclo de vida de arquivos uploadados para workflows."""

    def _workflow_dir(self, workflow_id: str) -> Path:
        path = Path(settings.WORKFLOW_UPLOAD_DIR) / workflow_id
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

    def save(
        self,
        workflow_id: str,
        filename: str,
        content: bytes,
    ) -> dict[str, str]:
        """Persiste o arquivo e retorna {file_id, url} onde url e o path absoluto."""
        suffix = Path(filename).suffix.lower()
        file_id = str(uuid.uuid4())
        dest = self._workflow_dir(workflow_id) / f"{file_id}{suffix}"
        dest.write_bytes(content)

        index = self._load_index(workflow_id)
        index[file_id] = {
            "original_filename": filename,
            "path": str(dest.resolve()),
        }
        self._save_index(workflow_id, index)
        return {"file_id": file_id, "url": str(dest.resolve())}

    def resolve_url(self, workflow_id: str, file_id: str) -> str | None:
        """Resolve file_id para o path absoluto do arquivo, ou None se nao existir."""
        index = self._load_index(workflow_id)
        entry = index.get(file_id)
        if entry is None:
            return None
        path = entry.get("path", "")
        if not Path(path).exists():
            return None
        return path

    def list_files(self, workflow_id: str) -> list[dict[str, Any]]:
        """Lista todos os arquivos do workflow com seus metadados."""
        index = self._load_index(workflow_id)
        return [
            {"file_id": fid, **meta}
            for fid, meta in index.items()
        ]


workflow_file_upload_service = WorkflowFileUploadService()
