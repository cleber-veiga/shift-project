"use client"

import { useEffect, useState } from "react"

import {
  fetchPredictedSchema,
  type FieldDescriptor,
} from "@/lib/auth"

export interface PredictedSchemaState {
  schema: FieldDescriptor[] | null
  predicted: boolean
  isLoading: boolean
  error: string | null
}

// Cache em escopo de módulo evita flicker quando o usuário troca entre nós
// no mesmo workflow — o schema raramente muda dentro da mesma sessão de
// edição. TTL de 30s casa com a janela de uma sessão de config típica.
type CacheEntry = { value: PredictedSchemaState; ts: number }
const _cache = new Map<string, CacheEntry>()
const _CACHE_TTL_MS = 30_000

function _cacheKey(workflowId: string, nodeId: string): string {
  return `${workflowId}:${nodeId}`
}

export function usePredictedSchema(
  workflowId: string | null | undefined,
  nodeId: string | null | undefined,
): PredictedSchemaState {
  const [state, setState] = useState<PredictedSchemaState>(() => {
    if (!workflowId || !nodeId) {
      return { schema: null, predicted: false, isLoading: false, error: null }
    }
    const cached = _cache.get(_cacheKey(workflowId, nodeId))
    if (cached && Date.now() - cached.ts < _CACHE_TTL_MS) {
      return cached.value
    }
    return { schema: null, predicted: false, isLoading: true, error: null }
  })

  useEffect(() => {
    if (!workflowId || !nodeId) {
      setState({ schema: null, predicted: false, isLoading: false, error: null })
      return
    }

    const key = _cacheKey(workflowId, nodeId)
    const cached = _cache.get(key)
    if (cached && Date.now() - cached.ts < _CACHE_TTL_MS) {
      setState(cached.value)
      return
    }

    let cancelled = false
    setState((s) => ({ ...s, isLoading: true, error: null }))

    fetchPredictedSchema(workflowId, nodeId)
      .then((res) => {
        if (cancelled) return
        const next: PredictedSchemaState = {
          schema: res.schema,
          predicted: res.predicted,
          isLoading: false,
          error: null,
        }
        _cache.set(key, { value: next, ts: Date.now() })
        setState(next)
      })
      .catch((err: unknown) => {
        if (cancelled) return
        const msg = err instanceof Error ? err.message : "Erro ao carregar schema"
        setState({ schema: null, predicted: false, isLoading: false, error: msg })
      })

    return () => {
      cancelled = true
    }
  }, [workflowId, nodeId])

  return state
}

// Helpers usados pelos node configs para validar referências contra o schema.

export function isColumnInSchema(
  schema: FieldDescriptor[] | null,
  column: string,
): boolean {
  if (!schema) return true // sem schema previsto, não temos como invalidar
  return schema.some((f) => f.name === column)
}

export function staleColumns(
  schema: FieldDescriptor[] | null,
  columns: string[],
): string[] {
  if (!schema) return []
  const known = new Set(schema.map((f) => f.name))
  const seen = new Set<string>()
  const result: string[] = []
  for (const c of columns) {
    if (!c) continue
    if (!known.has(c) && !seen.has(c)) {
      seen.add(c)
      result.push(c)
    }
  }
  return result
}
