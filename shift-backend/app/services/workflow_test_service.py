"""
Servico de teste de workflows: execucao inline com SSE, sem Prefect.

Executa nos em ordem topologica, emitindo eventos SSE por no.
Usa sessions independentes para nao bloquear o loop de eventos enquanto
queries externas correm em threadpool.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections import defaultdict, deque
from datetime import date, datetime, timezone
from typing import Any, AsyncGenerator
from uuid import UUID

from sqlalchemy import or_, select, update

from app.db.session import async_session_factory
from app.models import Project
from app.models.connection import Connection
from app.models.workflow import Workflow, WorkflowExecution
from app.services.connection_service import _collect_connection_ids, connection_service
from app.services.extraction_service import extraction_service
from app.services.load_service import load_service

_MAX_ROWS = 200
_SSE_PREVIEW_ROWS = 100  # maximo de linhas enviadas por SSE em modo producao


class WorkflowTestService:
    """Executa um workflow node-a-node e emite linhas SSE."""

    async def run_streaming(
        self,
        workflow_id: UUID,
        target_node_id: str | None = None,
        mode: str | None = None,
    ) -> AsyncGenerator[str, None]:
        def sse(payload: dict) -> str:
            return f"data: {json.dumps(payload, default=str)}\n\n"

        # ── 1. Carrega workflow + conexoes + cria registro de execucao ─────────
        async with async_session_factory() as db:
            result = await db.execute(select(Workflow).where(Workflow.id == workflow_id))
            workflow = result.scalar_one_or_none()

            if workflow is None:
                yield sse({"type": "error", "error": f"Workflow '{workflow_id}' nao encontrado."})
                return

            # Deriva modo de execucao do status do workflow se nao informado
            if mode is None:
                mode = "production" if workflow.status == "published" else "test"

            workspace_id: UUID | None = workflow.workspace_id
            if workspace_id is None and workflow.project_id is not None:
                r = await db.execute(
                    select(Project.workspace_id).where(Project.id == workflow.project_id)
                )
                workspace_id = r.scalar_one_or_none()

            try:
                conn_map = await _load_connections(
                    db, workflow.definition, workflow.project_id, workspace_id
                )
            except ValueError as exc:
                yield sse({"type": "error", "error": str(exc)})
                return

            exec_obj = WorkflowExecution(workflow_id=workflow.id, status="RUNNING")
            db.add(exec_obj)
            await db.flush()
            execution_id: UUID = exec_obj.id
            await db.commit()

        # ── 2. Executa nos em ordem topologica ────────────────────────────────
        nodes = workflow.definition.get("nodes", [])
        edges = workflow.definition.get("edges", [])
        ordered_ids = _topological_sort(nodes, edges)
        node_map = {n["id"]: n for n in nodes}

        # Se target_node_id informado, executa somente ate esse no (inclusive)
        if target_node_id and target_node_id in node_map:
            # Descobre quais nos sao ancestrais do target (+ o proprio)
            required: set[str] = set()
            _collect_ancestors(target_node_id, edges, node_map, required)
            ordered_ids = [nid for nid in ordered_ids if nid in required]

        total_start = time.monotonic()

        yield sse({
            "type": "execution_start",
            "execution_id": str(execution_id),
            "node_count": len(ordered_ids),
            "mode": mode,
            "timestamp": _ts(),
        })

        upstream: dict[str, Any] = {}
        final_status = "SUCCESS"

        for node_id in ordered_ids:
            node = node_map.get(node_id)
            if node is None:
                continue

            node_type = node.get("type") or node.get("data", {}).get("type", "unknown")
            label: str = node.get("data", {}).get("label") or node_type

            # Nó com dados fixados (Pin Data) — usa output salvo, pula execução
            pinned_output = node.get("data", {}).get("pinnedOutput")
            if pinned_output:
                upstream[node_id] = pinned_output
                yield sse({
                    "type": "node_complete",
                    "node_id": node_id,
                    "label": label,
                    "output": pinned_output,
                    "duration_ms": 0,
                    "is_pinned": True,
                    "timestamp": _ts(),
                })
                continue

            # Nó desativado — pula silenciosamente
            if node.get("data", {}).get("enabled") is False:
                upstream[node_id] = {"status": "skipped", "message": "Nó desativado."}
                yield sse({
                    "type": "node_complete",
                    "node_id": node_id,
                    "label": label,
                    "output": {"status": "skipped", "message": "Nó desativado."},
                    "duration_ms": 0,
                    "timestamp": _ts(),
                })
                continue

            yield sse({
                "type": "node_start",
                "node_id": node_id,
                "node_type": node_type,
                "label": label,
                "timestamp": _ts(),
            })

            t0 = time.monotonic()
            try:
                output = await _execute_node(node, upstream, conn_map, edges, mode)
                ms = int((time.monotonic() - t0) * 1000)
                upstream[node_id] = output
                # Em producao, envia apenas preview para nao sobrecarregar SSE
                sse_output = _trim_for_sse(output) if mode == "production" else output
                yield sse({
                    "type": "node_complete",
                    "node_id": node_id,
                    "label": label,
                    "output": sse_output,
                    "duration_ms": ms,
                    "timestamp": _ts(),
                })
            except Exception as exc:
                ms = int((time.monotonic() - t0) * 1000)
                final_status = "FAILED"
                yield sse({
                    "type": "node_error",
                    "node_id": node_id,
                    "label": label,
                    "error": str(exc),
                    "duration_ms": ms,
                    "timestamp": _ts(),
                })
                break

        total_ms = int((time.monotonic() - total_start) * 1000)

        # ── 3. Persiste status final ──────────────────────────────────────────
        async with async_session_factory() as db:
            await db.execute(
                update(WorkflowExecution)
                .where(WorkflowExecution.id == execution_id)
                .values(status=final_status, completed_at=datetime.now(timezone.utc))
            )
            await db.commit()

        yield sse({
            "type": "execution_complete",
            "execution_id": str(execution_id),
            "status": final_status,
            "duration_ms": total_ms,
            "timestamp": _ts(),
        })


# ─── Carregamento de conexoes ──────────────────────────────────────────────────

async def _load_connections(
    db: Any,
    definition: dict[str, Any],
    project_id: UUID | None,
    workspace_id: UUID | None,
) -> dict[str, Connection]:
    conn_id_strs = _collect_connection_ids(definition)
    if not conn_id_strs:
        return {}

    scope_filters = []
    if workspace_id is not None:
        scope_filters.append(Connection.workspace_id == workspace_id)
    if project_id is not None:
        scope_filters.append(Connection.project_id == project_id)
    if not scope_filters:
        raise ValueError("Escopo nao determinado para resolucao de conexoes.")

    result = await db.execute(
        select(Connection).where(
            Connection.id.in_([UUID(s) for s in conn_id_strs]),
            or_(*scope_filters),
        )
    )
    found: dict[str, Connection] = {str(c.id): c for c in result.scalars().all()}

    missing = [cid for cid in conn_id_strs if cid not in found]
    if missing:
        raise ValueError(f"Conexao '{missing[0]}' nao encontrada no escopo autorizado.")

    return found


# ─── Despachante de nos ────────────────────────────────────────────────────────

async def _execute_node(
    node: dict,
    upstream: dict[str, Any],
    conn_map: dict[str, Connection],
    edges: list[dict],
    mode: str = "test",
) -> dict[str, Any]:
    node_type = node.get("type") or node.get("data", {}).get("type", "unknown")
    data = node.get("data", {})
    node_id = node["id"]

    # ── Gatilhos ──────────────────────────────────────────────────────────────
    if node_type == "manual":
        return {
            "trigger_type": "manual",
            "status": "triggered",
            "message": "Gatilho manual ativado.",
        }

    # ── Entrada ───────────────────────────────────────────────────────────────
    if node_type == "sql_database":
        return await _exec_sql_database(node_id, data, conn_map, mode)

    if node_type == "inline_data":
        return _exec_inline_data(data)

    # ── Transformação ─────────────────────────────────────────────────────────
    if node_type == "mapper":
        return _exec_mapper(node_id, data, upstream, edges)

    if node_type == "filter":
        return _exec_filter(node_id, data, upstream, edges)

    # ── Saída ─────────────────────────────────────────────────────────────────
    if node_type == "truncate_table":
        return await _exec_truncate_table(node_id, data, upstream, edges, conn_map)

    if node_type == "bulk_insert":
        return await _exec_bulk_insert(node_id, data, upstream, edges, conn_map)

    if node_type == "loadNode":
        return await _exec_load_node(node_id, data, upstream, edges, conn_map)

    # ── Decisão ───────────────────────────────────────────────────────────────
    if node_type == "if_node":
        return _exec_if_node(node_id, data, upstream, edges)

    if node_type == "switch_node":
        return _exec_switch_node(node_id, data, upstream, edges)

    # Pass-through para nos nao implementados
    return {
        "status": "skipped",
        "node_type": node_type,
        "message": f"No '{node_type}' ainda nao implementado no modo de teste.",
    }


# ─── Inline Data ──────────────────────────────────────────────────────────────

def _exec_inline_data(data: dict) -> dict[str, Any]:
    """Retorna dados estáticos definidos no nó."""
    raw = data.get("data", [])
    rows: list[dict] = raw if isinstance(raw, list) else []
    # Garante que todos os items sao dicts
    rows = [r for r in rows if isinstance(r, dict)]
    columns = list(rows[0].keys()) if rows else []
    return {
        "row_count": len(rows),
        "columns": columns,
        "rows": rows,
    }


# ─── Mapper (Set) ─────────────────────────────────────────────────────────────

_MAPPER_TRANSFORMS: dict[str, Any] = {
    "upper":          lambda v: str(v).upper(),
    "lower":          lambda v: str(v).lower(),
    "trim":           lambda v: str(v).strip(),
    "remove_special": lambda v: re.sub(r"[^A-Za-z0-9 ]", "", str(v)),
    "only_digits":    lambda v: re.sub(r"[^0-9]", "", str(v)),
}


def _safe_cast(val: Any, field_type: str | None) -> Any:
    """Tenta converter o valor para o tipo informado (equivale ao TRY_CAST)."""
    if val is None or not field_type:
        return val
    try:
        if field_type == "integer":
            return int(float(val))
        if field_type == "float":
            return float(val)
        if field_type == "boolean":
            if isinstance(val, str):
                return val.lower() in ("true", "1", "yes", "sim")
            return bool(val)
        if field_type == "date":
            return str(date.fromisoformat(str(val)[:10]))
        if field_type == "datetime":
            return str(datetime.fromisoformat(str(val)))
        # string ou desconhecido
        return str(val)
    except (ValueError, TypeError):
        return None


_EXPR_TOKEN_RE = re.compile(r"(\{\{[^}]+\}\}|\$[a-zA-Z_]+)")

_SYSTEM_VARS = {
    "$now":   lambda: datetime.now(timezone.utc).isoformat(),
    "$today": lambda: date.today().isoformat(),
}


def _eval_expr_template(template: str, row: dict) -> str:
    """
    Evaluate an expression template by substituting {{FIELD}} with row
    values and $var with system variable values.  Returns concatenated string.
    """
    parts: list[str] = []
    last = 0
    for m in _EXPR_TOKEN_RE.finditer(template):
        if m.start() > last:
            parts.append(template[last:m.start()])
        tok = m.group(1)
        if tok.startswith("{{"):
            field = tok[2:-2]
            val = row.get(field)
            parts.append(str(val) if val is not None else "")
        else:
            resolver = _SYSTEM_VARS.get(tok)
            parts.append(resolver() if resolver else tok)
        last = m.end()
    if last < len(template):
        parts.append(template[last:])
    return "".join(parts)


def _exec_mapper(
    node_id: str,
    data: dict,
    upstream: dict[str, Any],
    edges: list[dict],
) -> dict[str, Any]:
    """
    Renomeia, transforma e/ou cria campos nas linhas upstream.

    Cada mapeamento pode ser:
      - campo de entrada (valueType="field"): pega valor da coluna source
      - valor fixo (valueType="static"): usa o valor literal informado
      - expressao (valueType="expression"): template com {{CAMPO}} e $var
    Transforms (upper, lower, trim, remove_special, only_digits, remove_chars, replace) sao aplicados em sequencia.
    O type (string, integer, float, boolean, date, datetime) aplica cast.
    """
    rows = _get_upstream_rows(node_id, upstream, edges)
    if not rows:
        return {"row_count": 0, "columns": [], "rows": [], "message": "Sem dados upstream."}

    mappings: list[dict] = data.get("mappings", [])
    drop_unmapped: bool = bool(data.get("drop_unmapped", False))

    if not mappings:
        columns = list(rows[0].keys()) if rows else []
        return {"row_count": len(rows), "columns": columns, "rows": rows}

    mapped_rows: list[dict] = []
    for row in rows:
        new_row: dict = {}
        mapped_sources: set[str] = set()

        for m in mappings:
            target = m.get("target")
            if not target:
                continue

            source = m.get("source")
            value_type = m.get("valueType", "field")
            transforms: list = m.get("transforms") or []
            field_type: str | None = m.get("type")

            # Resolve raw value
            if value_type == "expression":
                expr_template: str = m.get("exprTemplate") or ""
                if not expr_template:
                    continue
                val = _eval_expr_template(expr_template, row)
                # Track used fields
                for fmatch in re.finditer(r"\{\{([^}]+)\}\}", expr_template):
                    mapped_sources.add(fmatch.group(1))
            elif value_type == "static":
                val = m.get("value", "")
            elif source:
                val = row.get(source)
                mapped_sources.add(source)
            else:
                continue

            # Apply transforms (field mode only)
            # Each entry can be a string (simple) or dict {id, params} (parametrized)
            if value_type == "field" and transforms and val is not None:
                for t_entry in transforms:
                    if isinstance(t_entry, str):
                        t_id     = t_entry
                        t_params: dict = {}
                    else:
                        t_id     = str(t_entry.get("id", ""))
                        t_params = dict(t_entry.get("params") or {})

                    fn = _MAPPER_TRANSFORMS.get(t_id)
                    if fn:
                        val = fn(val)
                    elif t_id == "remove_chars":
                        chars = t_params.get("chars", "")
                        if chars:
                            val = re.sub(f"[{re.escape(chars)}]", "", str(val))
                    elif t_id == "replace":
                        from_str = t_params.get("from", "")
                        to_str   = t_params.get("to", "")
                        if from_str:
                            val = str(val).replace(from_str, to_str)
                    elif t_id == "truncate":
                        try:
                            length = int(t_params.get("length", "0"))
                        except (ValueError, TypeError):
                            length = 0
                        if length > 0:
                            val = str(val)[:length]

            # Apply type cast
            val = _safe_cast(val, field_type)

            new_row[target] = val

        # Include unmapped fields
        if not drop_unmapped:
            for key, v in row.items():
                if key not in mapped_sources and key not in new_row:
                    new_row[key] = v

        mapped_rows.append(new_row)

    columns = list(mapped_rows[0].keys()) if mapped_rows else []
    return {
        "row_count": len(mapped_rows),
        "columns": columns,
        "rows": mapped_rows,
    }


# ─── Filter ───────────────────────────────────────────────────────────────────

def _exec_filter(
    node_id: str,
    data: dict,
    upstream: dict[str, Any],
    edges: list[dict],
) -> dict[str, Any]:
    """
    Filtra linhas upstream por condições.

    Cada condição: {"field": "col", "operator": "eq|neq|gt|gte|lt|lte|contains|startswith|endswith|is_null|is_not_null", "value": "..."}
    logic: "and" | "or"
    """
    rows = _get_upstream_rows(node_id, upstream, edges)
    if not rows:
        return {"row_count": 0, "columns": [], "rows": [], "message": "Sem dados upstream."}

    conditions: list[dict] = data.get("conditions", [])
    logic: str = data.get("logic", "and")

    if not conditions:
        columns = list(rows[0].keys()) if rows else []
        return {"row_count": len(rows), "columns": columns, "rows": rows}

    def eval_condition(row: dict, cond: dict) -> bool:
        field = cond.get("field", "")
        op = cond.get("operator", "eq")
        value = cond.get("value")
        cell = row.get(field)

        if op == "is_null":
            return cell is None
        if op == "is_not_null":
            return cell is not None

        cell_str = str(cell) if cell is not None else ""
        value_str = str(value) if value is not None else ""

        if op == "eq":
            return cell_str == value_str
        if op == "neq":
            return cell_str != value_str
        if op == "contains":
            return value_str.lower() in cell_str.lower()
        if op == "startswith":
            return cell_str.lower().startswith(value_str.lower())
        if op == "endswith":
            return cell_str.lower().endswith(value_str.lower())

        # Comparações numéricas
        try:
            cell_num = float(cell_str)
            value_num = float(value_str)
            if op == "gt":
                return cell_num > value_num
            if op == "gte":
                return cell_num >= value_num
            if op == "lt":
                return cell_num < value_num
            if op == "lte":
                return cell_num <= value_num
        except (ValueError, TypeError):
            pass

        return False

    def row_passes(row: dict) -> bool:
        results = [eval_condition(row, c) for c in conditions]
        return all(results) if logic == "and" else any(results)

    filtered = [r for r in rows if row_passes(r)]
    columns = list(filtered[0].keys()) if filtered else (list(rows[0].keys()) if rows else [])

    return {
        "row_count": len(filtered),
        "columns": columns,
        "rows": filtered,
        "total_input": len(rows),
        "filtered_out": len(rows) - len(filtered),
    }


# ─── SQL Database (leitura) ────────────────────────────────────────────────────

async def _exec_sql_database(
    node_id: str,
    data: dict,
    conn_map: dict[str, Connection],
    mode: str = "test",
) -> dict[str, Any]:
    from app.schemas.connection import ConnectionType

    connection_id = str(data.get("connection_id") or "").strip()
    if not connection_id:
        raise ValueError(f"No SQL '{node_id}': connection_id nao configurado.")

    conn = conn_map.get(connection_id)
    if conn is None:
        raise ValueError(f"No SQL '{node_id}': conexao '{connection_id}' nao encontrada.")

    query = (data.get("query") or "").strip()
    if not query:
        raise ValueError(f"No SQL '{node_id}': nenhuma query SQL configurada.")

    lowered = query.lstrip().lower()
    if not (lowered.startswith("select") or lowered.startswith("with")):
        raise ValueError(
            f"No SQL '{node_id}': apenas queries SELECT/WITH sao permitidas."
        )

    if mode == "production":
        # Producao: sem limite (0 = busca todas as linhas)
        max_rows = 0
    else:
        # Teste: limitado a _MAX_ROWS
        max_rows = min(int(data.get("max_rows") or _MAX_ROWS), _MAX_ROWS)

    firebird_config = None
    if conn.type == ConnectionType.firebird.value:
        firebird_config = {
            "host": conn.host,
            "port": conn.port,
            "database": conn.database,
            "username": conn.username,
            "password": conn.password,
        }
        if conn.extra_params:
            firebird_config.update(conn.extra_params)

    conn_str = connection_service.build_connection_string(conn)

    result = await asyncio.to_thread(
        extraction_service.extract_sql,
        conn_str,
        conn.type,
        query,
        max_rows=max_rows,
        firebird_config=firebird_config,
    )
    return result.to_dict()


# ─── Load Node (escrita SQL) ───────────────────────────────────────────────────

async def _exec_truncate_table(
    node_id: str,
    data: dict,
    upstream: dict[str, Any],
    edges: list[dict],
    conn_map: dict[str, Connection],
) -> dict[str, Any]:
    """Limpa (TRUNCATE ou DELETE) uma tabela de destino e repassa dados upstream."""
    from app.schemas.connection import ConnectionType

    connection_id = str(data.get("connection_id") or "").strip()
    if not connection_id:
        raise ValueError(f"No '{node_id}': connection_id nao configurado.")

    conn = conn_map.get(connection_id)
    if conn is None:
        raise ValueError(f"No '{node_id}': conexao '{connection_id}' nao encontrada.")

    target_table = (data.get("target_table") or "").strip()
    if not target_table:
        raise ValueError(f"No '{node_id}': tabela de destino nao configurada.")

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', target_table):
        raise ValueError(f"No '{node_id}': nome de tabela invalido '{target_table}'.")

    mode: str = data.get("mode", "truncate")
    where_clause: str = (data.get("where_clause") or "").strip()

    if conn.type == ConnectionType.firebird.value:
        raise ValueError(f"No '{node_id}': operacao em Firebird nao suportada no modo de teste.")

    conn_str = connection_service.build_connection_string(conn)

    truncate_result = await asyncio.to_thread(
        load_service.truncate,
        conn_str,
        conn.type,
        target_table,
        mode=mode,
        where_clause=where_clause or None,
    )

    # Repassa dados upstream sem alteracao
    upstream_rows = _get_upstream_rows(node_id, upstream, edges)
    output = truncate_result.to_dict()
    if upstream_rows:
        output["row_count"] = len(upstream_rows)
        output["columns"] = list(upstream_rows[0].keys())
        output["rows"] = upstream_rows

    return output


async def _exec_bulk_insert(
    node_id: str,
    data: dict,
    upstream: dict[str, Any],
    edges: list[dict],
    conn_map: dict[str, Connection],
) -> dict[str, Any]:
    """Insere linhas upstream em uma tabela de destino com mapeamento de colunas.

    Delega para load_service que faz introspeccao dos tipos da tabela destino
    e converte os valores automaticamente para evitar erros de tipo (ex: ORA-01722).
    """
    from app.schemas.connection import ConnectionType

    connection_id = str(data.get("connection_id") or "").strip()
    if not connection_id:
        raise ValueError(f"No '{node_id}': connection_id nao configurado.")

    conn = conn_map.get(connection_id)
    if conn is None:
        raise ValueError(f"No '{node_id}': conexao '{connection_id}' nao encontrada.")

    target_table = (data.get("target_table") or "").strip()
    if not target_table:
        raise ValueError(f"No '{node_id}': tabela de destino nao configurada.")

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', target_table):
        raise ValueError(f"No '{node_id}': nome de tabela invalido '{target_table}'.")

    column_mapping: list[dict] = data.get("column_mapping") or []
    if not column_mapping:
        raise ValueError(f"No '{node_id}': mapeamento de colunas nao configurado.")

    valid_maps = [m for m in column_mapping if m.get("source") and m.get("target")]
    if not valid_maps:
        raise ValueError(f"No '{node_id}': nenhum mapeamento de colunas valido.")

    batch_size: int = int(data.get("batch_size", 1000))
    unique_columns: list[str] = data.get("unique_columns") or []
    rows = _get_upstream_rows(node_id, upstream, edges)

    if not rows:
        return {
            "status": "skipped",
            "message": "Sem dados upstream para inserir.",
            "rows_written": 0,
            "target_table": target_table,
        }

    if conn.type == ConnectionType.firebird.value:
        raise ValueError(f"No '{node_id}': escrita em Firebird nao suportada no modo de teste.")

    conn_str = connection_service.build_connection_string(conn)

    result = await asyncio.to_thread(
        load_service.insert,
        conn_str,
        conn.type,
        target_table,
        rows,
        column_mapping=valid_maps,
        batch_size=batch_size,
        unique_columns=unique_columns if unique_columns else None,
    )

    output = result.to_dict()
    parts = [f"{result.rows_written} registros inseridos em '{target_table}'."]
    if result.duplicates_removed > 0:
        parts.append(f"{result.duplicates_removed} duplicatas removidas.")
    if result.dest_count_after >= 0:
        parts.append(f"Total na tabela: {result.dest_count_after}.")
    output["message"] = " ".join(parts)
    return output


async def _exec_load_node(
    node_id: str,
    data: dict,
    upstream: dict[str, Any],
    edges: list[dict],
    conn_map: dict[str, Connection],
) -> dict[str, Any]:
    """Grava linhas upstream em uma tabela SQL de destino.

    Delega para load_service que faz introspeccao de tipos e cast automatico.
    """
    from app.schemas.connection import ConnectionType

    connection_id = str(data.get("connection_id") or "").strip()
    if not connection_id:
        raise ValueError(f"No '{node_id}': connection_id nao configurado.")

    conn = conn_map.get(connection_id)
    if conn is None:
        raise ValueError(f"No '{node_id}': conexao '{connection_id}' nao encontrada.")

    target_table = (data.get("target_table") or "").strip()
    if not target_table:
        raise ValueError(f"No '{node_id}': tabela de destino nao configurada.")

    if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', target_table):
        raise ValueError(f"No '{node_id}': nome de tabela invalido '{target_table}'.")

    write_disposition: str = data.get("write_disposition", "append")
    unique_columns: list[str] = data.get("unique_columns") or []
    rows = _get_upstream_rows(node_id, upstream, edges)

    if not rows:
        return {
            "status": "skipped",
            "message": "Sem dados upstream para carregar.",
            "rows_written": 0,
            "target_table": target_table,
        }

    if conn.type == ConnectionType.firebird.value:
        raise ValueError(f"No '{node_id}': escrita em Firebird nao suportada no modo de teste.")

    conn_str = connection_service.build_connection_string(conn)

    result = await asyncio.to_thread(
        load_service.insert,
        conn_str,
        conn.type,
        target_table,
        rows,
        write_disposition=write_disposition,
        unique_columns=unique_columns if unique_columns else None,
    )

    return result.to_dict()




# ─── IF Node (decisao binaria) ────────────────────────────────────────────────

def _exec_if_node(
    node_id: str,
    data: dict,
    upstream: dict[str, Any],
    edges: list[dict],
) -> dict[str, Any]:
    """
    Avalia condicoes sobre cada linha upstream e divide em dois branches:
    ``true`` (linhas que passam) e ``false`` (linhas que nao passam).

    Retorna formato ``__branches`` para que ``_get_upstream_rows`` escolha
    o branch correto via ``sourceHandle``.
    """
    rows = _get_upstream_rows(node_id, upstream, edges)
    conditions: list[dict] = data.get("conditions", [])
    logic: str = data.get("logic", "and")

    if not conditions:
        # Sem condicoes: tudo vai para true
        columns = list(rows[0].keys()) if rows else []
        branch = {"row_count": len(rows), "columns": columns, "rows": rows}
        return {
            "__branches": {
                "true": branch,
                "false": {"row_count": 0, "columns": columns, "rows": []},
            },
            "row_count": len(rows),
            "true_count": len(rows),
            "false_count": 0,
        }

    def _eval_cond(row: dict, cond: dict) -> bool:
        field = cond.get("field", "")
        op = cond.get("operator", "eq")
        value = cond.get("value")
        cell = row.get(field)

        if op == "is_null":
            return cell is None
        if op == "is_not_null":
            return cell is not None

        cell_str = str(cell) if cell is not None else ""
        value_str = str(value) if value is not None else ""

        if op == "eq":
            return cell_str == value_str
        if op == "neq":
            return cell_str != value_str
        if op == "contains":
            return value_str.lower() in cell_str.lower()
        if op == "startswith":
            return cell_str.lower().startswith(value_str.lower())
        if op == "endswith":
            return cell_str.lower().endswith(value_str.lower())

        try:
            cell_num = float(cell_str)
            value_num = float(value_str)
            if op == "gt":
                return cell_num > value_num
            if op == "gte":
                return cell_num >= value_num
            if op == "lt":
                return cell_num < value_num
            if op == "lte":
                return cell_num <= value_num
        except (ValueError, TypeError):
            pass

        return False

    def _row_passes(row: dict) -> bool:
        results = [_eval_cond(row, c) for c in conditions]
        return all(results) if logic == "and" else any(results)

    true_rows: list[dict] = []
    false_rows: list[dict] = []
    for row in rows:
        if _row_passes(row):
            true_rows.append(row)
        else:
            false_rows.append(row)

    columns = list(rows[0].keys()) if rows else []

    return {
        "__branches": {
            "true": {"row_count": len(true_rows), "columns": columns, "rows": true_rows},
            "false": {"row_count": len(false_rows), "columns": columns, "rows": false_rows},
        },
        "row_count": len(rows),
        "true_count": len(true_rows),
        "false_count": len(false_rows),
    }


# ─── Switch Node (decisao multipla) ──────────────────────────────────────────

def _exec_switch_node(
    node_id: str,
    data: dict,
    upstream: dict[str, Any],
    edges: list[dict],
) -> dict[str, Any]:
    """
    Avalia o valor de um campo em cada linha e distribui entre N branches
    nomeados (cases).  Linhas que nao casam com nenhum case vao para
    o branch ``default``.

    Retorna formato ``__branches`` com uma entrada por case + default.
    """
    rows = _get_upstream_rows(node_id, upstream, edges)
    switch_field: str = (data.get("switch_field") or "").strip()
    cases: list[dict] = data.get("cases", [])

    columns = list(rows[0].keys()) if rows else []

    if not switch_field or not cases:
        branch = {"row_count": len(rows), "columns": columns, "rows": rows}
        branches: dict[str, Any] = {"default": branch}
        for c in cases:
            label = c.get("label", "")
            if label:
                branches[label] = {"row_count": 0, "columns": columns, "rows": []}
        return {
            "__branches": branches,
            "row_count": len(rows),
        }

    # Monta mapa valor → label para lookup rapido
    value_to_label: dict[str, str] = {}
    for c in cases:
        label = c.get("label", "")
        for v in (c.get("values") or []):
            value_to_label[str(v).strip()] = label

    # Distribui linhas
    buckets: dict[str, list[dict]] = {c.get("label", ""): [] for c in cases if c.get("label")}
    buckets["default"] = []

    for row in rows:
        cell = row.get(switch_field)
        cell_str = str(cell).strip() if cell is not None else ""
        target_label = value_to_label.get(cell_str)
        if target_label and target_label in buckets:
            buckets[target_label].append(row)
        else:
            buckets["default"].append(row)

    branches_out: dict[str, Any] = {}
    for label, bucket_rows in buckets.items():
        branches_out[label] = {
            "row_count": len(bucket_rows),
            "columns": columns,
            "rows": bucket_rows,
        }

    result: dict[str, Any] = {
        "__branches": branches_out,
        "row_count": len(rows),
    }
    for label, bucket_rows in buckets.items():
        result[f"{label}_count"] = len(bucket_rows)

    return result


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _trim_for_sse(output: dict[str, Any]) -> dict[str, Any]:
    """Cria uma versao resumida do output para transporte via SSE.

    Em modo producao, os nos podem produzir milhares de linhas. Enviar tudo
    pelo SSE sobrecarregaria o frontend. Esta funcao mantém apenas as
    primeiras _SSE_PREVIEW_ROWS linhas e adiciona metadados de preview.
    """
    if not isinstance(output, dict):
        return output

    # Nos com branches (IF, Switch) — aplica trim em cada branch
    branches = output.get("__branches")
    if isinstance(branches, dict):
        trimmed = {**output}
        trimmed["__branches"] = {
            k: _trim_for_sse(v) for k, v in branches.items()
        }
        return trimmed

    # Nos com rows[]
    rows = output.get("rows")
    if not isinstance(rows, list) or len(rows) <= _SSE_PREVIEW_ROWS:
        return output

    trimmed = {**output}
    trimmed["rows"] = rows[:_SSE_PREVIEW_ROWS]
    trimmed["is_preview"] = True
    trimmed["total_rows"] = len(rows)
    return trimmed


def _get_upstream_rows(
    node_id: str,
    upstream: dict[str, Any],
    edges: list[dict],
) -> list[dict]:
    """
    Retorna as linhas do primeiro nó upstream que produziu dados tabulares.
    Segue a ordem dos edges para preservar a topologia do grafo.

    Suporta nós com múltiplas saídas (IF/Switch): se o output contem
    ``__branches``, usa o ``sourceHandle`` da edge para escolher o branch.
    """
    incoming = [e for e in edges if e.get("target") == node_id]
    for edge in incoming:
        src_id = edge["source"]
        source_handle = edge.get("sourceHandle")
        output = upstream.get(src_id, {})

        if not isinstance(output, dict):
            continue

        # Nó com múltiplas saídas (IF, Switch)
        branches = output.get("__branches")
        if isinstance(branches, dict) and source_handle:
            branch_data = branches.get(source_handle, {})
            if isinstance(branch_data, dict) and isinstance(branch_data.get("rows"), list):
                return branch_data["rows"]
            continue

        # Nó normal com saída única
        if isinstance(output.get("rows"), list):
            return output["rows"]

    return []


def _collect_ancestors(
    target: str,
    edges: list[dict],
    node_map: dict[str, dict],
    result: set[str],
) -> None:
    """Coleta recursivamente todos os ancestrais de *target* (inclusive)."""
    if target in result:
        return
    result.add(target)
    for edge in edges:
        if edge.get("target") == target:
            src = edge.get("source")
            if src and src in node_map:
                _collect_ancestors(src, edges, node_map, result)


def _topological_sort(nodes: list[dict], edges: list[dict]) -> list[str]:
    """Ordenacao topologica de Kahn — retorna IDs em ordem de execucao."""
    all_ids = [n["id"] for n in nodes]
    in_degree: dict[str, int] = {nid: 0 for nid in all_ids}
    adj: dict[str, list[str]] = defaultdict(list)

    for edge in edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src and tgt and src in in_degree and tgt in in_degree:
            adj[src].append(tgt)
            in_degree[tgt] += 1

    queue: deque[str] = deque(sorted(nid for nid in all_ids if in_degree[nid] == 0))
    result: list[str] = []

    while queue:
        cur = queue.popleft()
        result.append(cur)
        for nxt in sorted(adj[cur]):
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    # Anexa restantes (ciclos ou nos desconexos)
    seen = set(result)
    result.extend(nid for nid in all_ids if nid not in seen)
    return result


def _ts() -> str:
    return datetime.now(timezone.utc).isoformat()


workflow_test_service = WorkflowTestService()
