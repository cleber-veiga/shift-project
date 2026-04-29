"""
Perfil estático de execução por tipo de nó.

NODE_EXECUTION_PROFILE é um mapa imutável usado pelo StrategyObserver e,
futuramente, pelo StrategyResolver (Fase 5) para decidir como e onde rodar
cada nó sem consultar o banco.

Shape:
  - narrow  : transforma linhas 1-para-1 ou filtra (mapper, filter, math,
               record_id, sample, sort). Candidato a LOCAL_THREAD.
  - wide    : gera ou consome múltiplas fontes / reshapes (join, pivot,
               aggregator, union). Pode precisar de DATA_WORKER em volume.
  - io      : lê/escreve em sistema externo (sql_database, http_request,
               csv_input). Sempre IO_THREAD.
  - output  : grava resultado final (load, bulk_insert, composite_insert,
               truncate_table, notification, dead_letter). Sempre IO_THREAD.
  - control : controla fluxo sem dados próprios (triggers, if/switch, loop,
               sync, call_workflow, workflow_input/output). LOCAL_THREAD.

default_strategy (observação — não altera runner ainda na Fase 4):
  - local_thread : asyncio.to_thread com processor síncrono (atual).
  - data_worker  : futuro subprocess isolado (Fase 6).
  - io_thread    : asyncio.to_thread com I/O externo (atual, igual a local).
"""

from __future__ import annotations

NODE_EXECUTION_PROFILE: dict[str, dict[str, str]] = {
    # --- Triggers (control) ---
    "manual":           {"shape": "control", "default_strategy": "local_thread"},
    "webhook":          {"shape": "control", "default_strategy": "local_thread"},
    "cron":             {"shape": "control", "default_strategy": "local_thread"},
    "polling":          {"shape": "control", "default_strategy": "local_thread"},

    # --- Entradas de dados (io) ---
    "sql_database":     {"shape": "io",      "default_strategy": "io_thread"},
    "http_request":     {"shape": "io",      "default_strategy": "io_thread"},
    "csv_input":        {"shape": "io",      "default_strategy": "io_thread"},
    "excel_input":      {"shape": "io",      "default_strategy": "io_thread"},
    "api_input":        {"shape": "io",      "default_strategy": "io_thread"},
    "inline_data":      {"shape": "io",      "default_strategy": "local_thread"},
    "extractNode":      {"shape": "io",      "default_strategy": "io_thread"},
    "sql_script":       {"shape": "io",      "default_strategy": "io_thread"},

    # --- Transformações narrow (1-para-1 ou filtro) ---
    "filter":           {"shape": "narrow",  "default_strategy": "local_thread"},
    "mapper":           {"shape": "narrow",  "default_strategy": "local_thread"},
    "math":             {"shape": "narrow",  "default_strategy": "local_thread"},
    "record_id":        {"shape": "narrow",  "default_strategy": "local_thread"},
    "sample":           {"shape": "narrow",  "default_strategy": "local_thread"},
    "text_to_rows":     {"shape": "wide",    "default_strategy": "local_thread"},

    # --- Transformações wide (reshape / multi-input) ---
    "sort":             {"shape": "wide",    "default_strategy": "local_thread"},
    "aggregator":       {"shape": "wide",    "default_strategy": "local_thread"},
    "join":             {"shape": "wide",    "default_strategy": "data_worker"},
    "lookup":           {"shape": "wide",    "default_strategy": "data_worker"},
    "deduplication":    {"shape": "wide",    "default_strategy": "data_worker"},
    "union":            {"shape": "wide",    "default_strategy": "local_thread"},
    "pivot":            {"shape": "wide",    "default_strategy": "local_thread"},
    "unpivot":          {"shape": "wide",    "default_strategy": "local_thread"},
    "code":             {"shape": "wide",    "default_strategy": "local_thread"},

    # --- Saídas (output) ---
    "loadNode":         {"shape": "output",  "default_strategy": "io_thread"},
    "bulk_insert":      {"shape": "output",  "default_strategy": "io_thread"},
    "composite_insert": {"shape": "output",  "default_strategy": "io_thread"},
    "truncate_table":   {"shape": "output",  "default_strategy": "io_thread"},
    "notification":     {"shape": "output",  "default_strategy": "io_thread"},
    "dead_letter":      {"shape": "output",  "default_strategy": "io_thread"},
    "workflow_output":  {"shape": "output",  "default_strategy": "local_thread"},

    # --- Controle de fluxo ---
    "ifElse":           {"shape": "control", "default_strategy": "local_thread"},
    "switch":           {"shape": "control", "default_strategy": "local_thread"},
    "if_node":          {"shape": "control", "default_strategy": "local_thread"},
    "switch_node":      {"shape": "control", "default_strategy": "local_thread"},
    "assert":           {"shape": "control", "default_strategy": "local_thread"},
    "loop":             {"shape": "control", "default_strategy": "local_thread"},
    "sync":             {"shape": "control", "default_strategy": "local_thread"},

    # --- Sub-workflows ---
    "call_workflow":    {"shape": "control", "default_strategy": "local_thread"},
    "workflow_input":   {"shape": "control", "default_strategy": "local_thread"},
}


def get_profile(node_type: str) -> dict[str, str]:
    """Retorna o perfil do nó, com fallback para narrow/local_thread."""
    return NODE_EXECUTION_PROFILE.get(
        node_type,
        {"shape": "narrow", "default_strategy": "local_thread"},
    )
