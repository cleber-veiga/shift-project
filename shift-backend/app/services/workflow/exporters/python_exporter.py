"""
Exportador Python: workflow -> script standalone com duckdb + sqlalchemy.

O script gerado abre uma conexao DuckDB em memoria, materializa cada no
como tabela DuckDB na ordem topologica e imprime o resultado final.
``${var}`` vira ``os.environ['var']`` e ``connection_id`` vira uma constante
com TODO no topo do script.
"""

from __future__ import annotations

from typing import Any

from app.services.workflow.exporters._common import (
    classify_node,
    collect_connections,
    collect_referenced_vars,
    build_graph,
    export_metadata,
    get_handle_inputs,
    quote_ident,
    render_var_placeholders,
    sanitize_sql_identifier,
    short_connection_alias,
    sql_literal,
    topological_order,
)
from app.services.workflow.exporters.errors import UnsupportedNodeError
from app.services.workflow.exporters.sql_exporter import _HANDLERS as _SQL_HANDLERS


_HEADER_TEMPLATE = '''"""
Workflow: {workflow_name}
Workflow ID: {workflow_id}
Exported at: {exported_at}
Generator: Shift v{shift_version} (Python exporter)

Run:
    pip install duckdb{sa_extra}
{env_lines}
    python this_script.py
"""
import os
import duckdb
{extra_imports}

{connection_constants}
{var_constants}

def main() -> None:
    con = duckdb.connect(":memory:"){extra_attaches}

{body}

{final_print}


if __name__ == "__main__":
    main()
'''


class PythonExporter:
    """Converte ``WorkflowDefinition`` em script Python standalone (duckdb)."""

    def export(self, workflow_definition: dict[str, Any]) -> str:
        nodes = list(workflow_definition.get("nodes") or [])
        edges = list(workflow_definition.get("edges") or [])

        unsupported: list[dict[str, Any]] = []
        for node in nodes:
            status, reason = classify_node(node)
            if status == "unsupported":
                unsupported.append({
                    "node_id": str(node.get("id") or ""),
                    "node_type": str(node.get("type") or ""),
                    "reason": reason or "nao suportado",
                })
        if unsupported:
            raise UnsupportedNodeError(unsupported)

        adjacency, reverse_adj, in_degree, node_map, target_handle_map = build_graph(nodes, edges)
        order = topological_order(in_degree, adjacency)

        terminals: list[str] = []
        for node_id in order:
            ntype = str(node_map[node_id].get("type") or "")
            if ntype == "loadNode":
                continue
            downstream = adjacency.get(node_id) or []
            data_downstream = [
                d for d in downstream
                if str(node_map[d].get("type") or "") != "loadNode"
            ]
            if not data_downstream:
                terminals.append(node_id)

        meta = export_metadata(workflow_definition)
        var_refs = collect_referenced_vars(workflow_definition)
        conn_refs = collect_connections(workflow_definition)

        # Geramos o corpo aproveitando os mesmos handlers do SQL exporter:
        # sao funcoes puras que produzem o bloco SQL "CREATE OR REPLACE
        # TEMPORARY TABLE ..." — basta envolver em ``con.execute("""...""")``.
        body_blocks: list[str] = []
        for node_id in order:
            node = node_map[node_id]
            ntype = str(node.get("type") or "")
            handler = _SQL_HANDLERS.get(ntype)
            if handler is None:
                raise UnsupportedNodeError([{
                    "node_id": node_id,
                    "node_type": ntype,
                    "reason": "sem handler registrado no Python exporter",
                }])
            inputs = get_handle_inputs(node_id, reverse_adj, target_handle_map)
            sql_block = handler(node_id, node, inputs, node_map)
            body_blocks.append(_wrap_sql_in_python(node_id, ntype, sql_block))

        body_text = "\n\n".join(body_blocks)
        body_text = "\n".join("    " + line if line else "" for line in body_text.splitlines())

        # Constantes de variaveis e conexoes
        var_consts = _render_var_constants(var_refs)
        conn_consts = _render_connection_constants(conn_refs)

        # ATTACH automatico para cada conexao (executado dentro de main()).
        attach_lines = ""
        if conn_refs:
            attach_lines = "\n".join(
                f"\n    # TODO: confirm extension is loaded (e.g., con.execute(\"INSTALL postgres; LOAD postgres;\"))\n"
                f"    con.execute(f\"ATTACH '{{{short_connection_alias(cid).upper()}_URL}}' "
                f"AS {short_connection_alias(cid)} (TYPE POSTGRES, READ_ONLY)\")"
                for cid in sorted(conn_refs)
            )

        # Print do(s) terminal(is).
        if terminals:
            final_lines = []
            for t in terminals:
                tname = sanitize_sql_identifier(t)
                final_lines.append(f"    df = con.execute({_py_str(f'SELECT * FROM {quote_ident(tname)}')}).fetchdf()")
                final_lines.append(f"    print({_py_str(f'── {t} ──')})")
                final_lines.append("    print(df)")
            final_print = "\n".join(final_lines)
        else:
            final_print = "    pass  # No terminal output node detected."

        env_lines = "".join(
            f"    export {name}=...\n" for name in sorted(var_refs)
        )
        if env_lines:
            env_lines = env_lines.rstrip("\n")

        return _HEADER_TEMPLATE.format(
            workflow_name=meta.get("workflow_name") or "(unnamed)",
            workflow_id=meta.get("workflow_id") or "(no-id)",
            exported_at=meta["exported_at"],
            shift_version=meta["shift_version"],
            sa_extra="" if not conn_refs else " sqlalchemy",
            env_lines=env_lines or "    # (no environment variables required)",
            extra_imports="" if not conn_refs else "from sqlalchemy import create_engine  # noqa: F401",
            connection_constants=conn_consts,
            var_constants=var_consts,
            extra_attaches=attach_lines,
            body=body_text,
            final_print=final_print,
        )


def _wrap_sql_in_python(node_id: str, node_type: str, sql_block: str) -> str:
    """Empacota um bloco SQL em ``con.execute(\"\"\"...\"\"\")``.

    O bloco gerado pelo SQL exporter ja vem com comentario de cabecalho
    (``-- ── Node: ...``) — preservamos como comentario Python.
    """
    if node_type == "loadNode":
        # loadNode no SQL exporter ja e composto so de comentarios — preserva
        # como comentario Python.
        py_lines = []
        for line in sql_block.splitlines():
            stripped = line.lstrip("- ").rstrip()
            if stripped:
                py_lines.append(f"# {stripped}")
        return "\n".join(py_lines) or f"# loadNode {node_id}"

    # Separa o cabecalho de comentario do corpo SQL para um output mais limpo.
    lines = sql_block.splitlines()
    header_comments: list[str] = []
    body_lines: list[str] = []
    in_body = False
    for line in lines:
        if not in_body and line.lstrip().startswith("--"):
            header_comments.append(line.lstrip("- ").rstrip())
        else:
            in_body = True
            body_lines.append(line)
    body_sql = "\n".join(body_lines).rstrip().rstrip(";")

    # Triple-quoted: usamos """ e escapamos """ no body se houver (improvavel).
    safe_body = body_sql.replace('"""', '\\"\\"\\"')

    pieces: list[str] = [f"# {' '.join(header_comments)}".rstrip()]
    pieces.append(f'con.execute("""\n{safe_body}\n""")')
    return "\n".join(pieces)


def _render_var_constants(var_refs: dict[str, list[str]]) -> str:
    if not var_refs:
        return "# No workflow variables referenced."
    lines = ["# ── Workflow variables (read from environment) ──"]
    for name in sorted(var_refs):
        users = ", ".join(var_refs[name])
        lines.append(f"# {name} -- used in: {users}")
        lines.append(f"{name} = os.environ[{_py_str(name)}]")
    return "\n".join(lines)


def _render_connection_constants(conn_refs: dict[str, list[str]]) -> str:
    if not conn_refs:
        return "# No connections referenced."
    lines = ["# ── Connection URLs (configure before running) ──"]
    for cid in sorted(conn_refs):
        alias = short_connection_alias(cid)
        users = ", ".join(conn_refs[cid])
        env_name = f"{alias.upper()}_URL"
        lines.append(f"# {alias} (id={cid}) -- used in: {users}")
        lines.append(
            f"{env_name} = os.environ.get({_py_str(env_name)}, "
            f"{_py_str(f'postgresql://USER:PASS@HOST:PORT/DB')})"
        )
    return "\n".join(lines)


def _py_str(value: str) -> str:
    """repr() seguro: usa aspas duplas quando string contem apostrofo."""
    if "'" in value and '"' not in value:
        return '"' + value.replace("\\", "\\\\") + '"'
    return repr(value)
