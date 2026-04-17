"""
Testes da migracao ``a4b5c6d7e8f9_composite_upsert_defaults``.

A migracao normaliza blueprints existentes em ``custom_node_definitions``
adicionando ``conflict_mode='insert'``, ``conflict_keys=[]`` e
``update_columns=None`` em steps que nao os possuem.

Como o SQL ``CAST(:bp AS jsonb)`` e Postgres-only, nao rodamos a migracao
contra um banco real aqui. Em vez disso, mockamos ``op.get_bind()`` com
uma conexao fake que captura chamadas ``conn.execute()`` e inspecionamos
a logica de normalizacao diretamente.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from alembic import op as alembic_op


MIGRATION_PATH = (
    Path(__file__).parent.parent
    / "alembic" / "versions"
    / "2026_04_17_a4b5c6d7e8f9_composite_upsert_defaults.py"
)


def _load_migration() -> ModuleType:
    """Importa o modulo da migracao sem depender do Alembic CLI."""
    spec = importlib.util.spec_from_file_location("mig_a4b5", MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _FakeResult:
    """Simula o retorno de ``conn.execute(SELECT...)``."""

    def __init__(self, rows: list[tuple[Any, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple[Any, Any]]:
        return list(self._rows)


class _FakeConn:
    """Conexao simulada que captura todos os ``execute`` em ``calls``.

    Responde ``SELECT id, blueprint FROM custom_node_definitions`` com as
    rows pre-carregadas. Os UPDATEs sao apenas registrados.
    """

    def __init__(self, rows: list[tuple[Any, dict[str, Any] | None]]) -> None:
        self._rows = rows
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def execute(self, stmt: Any, params: dict[str, Any] | None = None):
        sql = str(stmt).strip()
        self.calls.append((sql, params))
        if sql.upper().startswith("SELECT"):
            return _FakeResult(self._rows)  # type: ignore[return-value]
        return None

    @property
    def updates(self) -> list[dict[str, Any]]:
        """Payloads dos UPDATEs emitidos — util para asserts."""
        out: list[dict[str, Any]] = []
        for sql, params in self.calls:
            if params is not None and sql.upper().startswith("UPDATE") and "bp" in params:
                out.append(
                    {
                        "id": params["id"],
                        "blueprint": json.loads(params["bp"]),
                    }
                )
        return out


@pytest.fixture
def migration() -> ModuleType:
    return _load_migration()


def _patch_bind(monkeypatch: pytest.MonkeyPatch, conn: _FakeConn) -> None:
    monkeypatch.setattr(alembic_op, "get_bind", lambda: conn)


class TestCompositeUpsertDefaultsMigration:
    """Testa upgrade/downgrade sem SQL real, inspecionando os UPDATEs."""

    def test_upgrade_fills_defaults_for_legacy_blueprint(
        self,
        monkeypatch: pytest.MonkeyPatch,
        migration: ModuleType,
    ) -> None:
        """Step sem os 3 campos recebe defaults conservadores."""
        legacy_blueprint = {
            "tables": [
                {
                    "alias": "nota",
                    "table": "NOTA",
                    "role": "header",
                    "columns": ["numero", "cliente_id"],
                    "returning": ["id"],
                    # sem conflict_mode / conflict_keys / update_columns
                },
            ]
        }
        conn = _FakeConn(rows=[("row-1", legacy_blueprint)])
        _patch_bind(monkeypatch, conn)

        migration.upgrade()

        assert len(conn.updates) == 1
        updated = conn.updates[0]
        assert updated["id"] == "row-1"
        step = updated["blueprint"]["tables"][0]
        assert step["conflict_mode"] == "insert"
        assert step["conflict_keys"] == []
        assert step["update_columns"] is None
        # Campos originais preservados.
        assert step["alias"] == "nota"
        assert step["columns"] == ["numero", "cliente_id"]

    def test_upgrade_is_idempotent_skips_already_normalized(
        self,
        monkeypatch: pytest.MonkeyPatch,
        migration: ModuleType,
    ) -> None:
        """Blueprint ja normalizado nao emite nenhum UPDATE."""
        normalized = {
            "tables": [
                {
                    "alias": "nota",
                    "table": "NOTA",
                    "role": "header",
                    "columns": ["numero"],
                    "returning": [],
                    "conflict_mode": "insert",
                    "conflict_keys": [],
                    "update_columns": None,
                },
            ]
        }
        conn = _FakeConn(rows=[("row-norm", normalized)])
        _patch_bind(monkeypatch, conn)

        migration.upgrade()

        assert conn.updates == []

    def test_upgrade_preserves_existing_upsert_mode(
        self,
        monkeypatch: pytest.MonkeyPatch,
        migration: ModuleType,
    ) -> None:
        """Step com conflict_mode='upsert' existente nao e sobrescrito.

        A migracao so adiciona campos ausentes — se ``conflict_mode`` ja
        existe como 'upsert', mantem. ``conflict_keys`` nao-default
        tambem e preservado.
        """
        modern = {
            "tables": [
                {
                    "alias": "nota",
                    "table": "NOTA",
                    "role": "header",
                    "columns": ["numero", "valor"],
                    "returning": ["id"],
                    "conflict_mode": "upsert",
                    "conflict_keys": ["numero"],
                    # update_columns ausente — deve receber default None
                },
            ]
        }
        conn = _FakeConn(rows=[("row-upsert", modern)])
        _patch_bind(monkeypatch, conn)

        migration.upgrade()

        # Apenas update_columns estava ausente -> um UPDATE.
        assert len(conn.updates) == 1
        step = conn.updates[0]["blueprint"]["tables"][0]
        assert step["conflict_mode"] == "upsert"
        assert step["conflict_keys"] == ["numero"]
        assert step["update_columns"] is None

    def test_downgrade_removes_phase2_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        migration: ModuleType,
    ) -> None:
        """Downgrade remove conflict_mode/conflict_keys/update_columns."""
        normalized = {
            "tables": [
                {
                    "alias": "nota",
                    "table": "NOTA",
                    "role": "header",
                    "columns": ["numero"],
                    "returning": [],
                    "conflict_mode": "insert",
                    "conflict_keys": [],
                    "update_columns": None,
                },
            ]
        }
        conn = _FakeConn(rows=[("row-dn", normalized)])
        _patch_bind(monkeypatch, conn)

        migration.downgrade()

        assert len(conn.updates) == 1
        step = conn.updates[0]["blueprint"]["tables"][0]
        assert "conflict_mode" not in step
        assert "conflict_keys" not in step
        assert "update_columns" not in step
        # Campos base preservados.
        assert step["alias"] == "nota"
        assert step["columns"] == ["numero"]

    def test_upgrade_skips_malformed_blueprint_gracefully(
        self,
        monkeypatch: pytest.MonkeyPatch,
        migration: ModuleType,
    ) -> None:
        """Rows com blueprint None / tables invalido / vazio sao puladas."""
        rows: list[tuple[Any, Any]] = [
            ("row-null", None),
            ("row-non-dict", "isto nao e um dict"),
            ("row-tables-str", {"tables": "nao e lista"}),
            ("row-tables-empty", {"tables": []}),
            ("row-empty-dict", {}),
        ]
        conn = _FakeConn(rows=rows)
        _patch_bind(monkeypatch, conn)

        # Nao deve levantar.
        migration.upgrade()

        # Nenhuma das linhas malformadas gera UPDATE.
        assert conn.updates == []
