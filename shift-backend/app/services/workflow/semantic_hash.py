"""
Hash semântico determinístico por nó (Fase 5).

compute_semantic_hash() produz um hash estável que:
  - Exclui campos runtime-only (cache_enabled, cache_ttl_seconds, force_refresh).
  - Para nós com connection_id, usa o ID (não a connection_string bruta).
  - Inclui fingerprints dos inputs upstream.
  - É versionado (algo_version) para invalidar caches quando a lógica muda.

Aplicado a: sql_database, join, lookup, aggregator.
Para outros tipos, o hash ainda pode ser calculado — só o skip automático
baseado nele é conservador (ver StrategyResolver).

Critério de aceite (benchmarking §5.2):
  100 runs idênticas → exatamente 1 hash distinto por nó cacheável.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Campos que não representam lógica de transformação — variam entre runs
# sem mudar o resultado. Excluídos do hash para evitar invalidação falsa.
RUNTIME_ONLY_FIELDS: frozenset[str] = frozenset({
    "cache_enabled",
    "cache_ttl_seconds",
    "force_refresh",
    "timeout_seconds",
    "retry_policy",
    "checkpoint_enabled",
    "pinnedOutput",
    "enabled",
    "label",
    "position",
})

# Campos sensíveis que NUNCA entram no hash (segurança + correto).
# connection_string é substituído por connection_id abaixo.
_SENSITIVE_FIELDS: frozenset[str] = frozenset({
    "connection_string",
    "password",
    "secret",
    "api_key",
})

# node_types adicionais a excluir campos extras (extensível).
_EXTRA_SKIP: dict[str, frozenset[str]] = {
    "sql_database": frozenset({"connection_string"}),
    "extractNode":  frozenset({"connection_string"}),
    "join":         frozenset({"connection_string"}),
    "lookup":       frozenset({"connection_string"}),
    "aggregator":   frozenset(),
}


def compute_semantic_hash(
    config: dict[str, Any],
    input_fingerprints: list[str],
    algo_version: int = 1,
    node_type: str = "",
) -> str:
    """Hash determinístico que ignora campos runtime-only.

    Parâmetros
    ----------
    config:
        Config bruta do nó (pode incluir campos runtime — serão excluídos).
    input_fingerprints:
        Lista de hashes/fingerprints dos inputs upstream, na ordem canônica.
        Garante que o hash muda quando upstream muda.
    algo_version:
        Incrementar para invalidar todos os caches sem mudar config.
    node_type:
        Tipo do nó — usado para excluir campos extras por tipo.

    Retorna
    -------
    str
        Hex digest SHA-256 de 64 caracteres (truncado a 32 para legibilidade).
    """
    cleaned = _clean_config(config, node_type)

    payload = {
        "v": algo_version,
        "node_type": node_type,
        "config": cleaned,
        "inputs": sorted(input_fingerprints),  # ordem canônica
    }

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:32]


def _clean_config(config: dict[str, Any], node_type: str) -> dict[str, Any]:
    """Remove campos runtime-only e sensíveis, normaliza connection_id."""
    extra_skip = _EXTRA_SKIP.get(node_type, frozenset())
    all_skip = RUNTIME_ONLY_FIELDS | _SENSITIVE_FIELDS | extra_skip

    cleaned: dict[str, Any] = {}
    for key, value in config.items():
        if key in all_skip:
            continue
        cleaned[key] = _normalize_value(key, value)

    return cleaned


def _normalize_value(key: str, value: Any) -> Any:
    """Normalização recursiva: listas são ordenadas quando possível."""
    if isinstance(value, dict):
        return {k: _normalize_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        # Listas de primitivos: ordenar para canonical form (ex: colunas selecionadas).
        # Listas de dicts: manter ordem (pode ser relevante, ex: conditions).
        if value and all(isinstance(i, (str, int, float, bool)) for i in value):
            return sorted(value, key=str)
        return [_normalize_value("", i) for i in value]
    return value


def fingerprint_schema(schema: list[dict[str, Any]]) -> str:
    """Fingerprint curto de um schema (lista de {name, data_type}).

    Usado para popular ``input_fingerprints`` quando o schema do upstream
    está disponível antes da execução.
    """
    canonical = json.dumps(
        sorted(schema, key=lambda f: f.get("name", "")),
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.md5(canonical.encode()).hexdigest()[:16]  # noqa: S324
