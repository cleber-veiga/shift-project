"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { ExecutionsFilters, type ExecutionFilterValues } from "./executions-filters"
import { ExecutionsList } from "./executions-list"
import { ExecutionsDetail } from "./executions-detail"
import {
  listExecutions,
  type ExecutionListResponse,
  type ExecutionStatus,
  type TriggeredBy,
} from "@/lib/api/executions"

interface ExecutionsTabProps {
  workflowId: string
  active: boolean
}

const DEFAULT_FILTERS: ExecutionFilterValues = {
  status: "",
  triggered_by: "",
  from: "",
  to: "",
}

const PAGE_SIZE = 20
const AUTO_REFRESH_BASE_MS = 10_000
const AUTO_REFRESH_MAX_MS = 60_000

function toIsoOrUndef(local: string): string | undefined {
  if (!local) return undefined
  const d = new Date(local)
  if (Number.isNaN(d.getTime())) return undefined
  return d.toISOString()
}

export function ExecutionsTab({ workflowId, active }: ExecutionsTabProps) {
  const [filters, setFilters] = useState<ExecutionFilterValues>(DEFAULT_FILTERS)
  const [page, setPage] = useState(1)
  const [data, setData] = useState<ExecutionListResponse>({
    items: [],
    total: 0,
    page: 1,
    size: PAGE_SIZE,
  })
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [autoRefresh, setAutoRefresh] = useState(false)

  // Evita corrida: a ultima request com request_id atual vence.
  const requestSeq = useRef(0)

  const load = useCallback(async (): Promise<boolean> => {
    if (workflowId === "new") {
      setData({ items: [], total: 0, page: 1, size: PAGE_SIZE })
      return true
    }
    const myId = ++requestSeq.current
    setLoading(true)
    setError(null)
    try {
      const resp = await listExecutions({
        workflowId,
        status: (filters.status as ExecutionStatus) || undefined,
        triggered_by: (filters.triggered_by as TriggeredBy) || undefined,
        from: toIsoOrUndef(filters.from),
        to: toIsoOrUndef(filters.to),
        page,
        size: PAGE_SIZE,
      })
      if (requestSeq.current === myId) setData(resp)
      return true
    } catch (e) {
      if (requestSeq.current === myId) {
        setError(e instanceof Error ? e.message : "Falha ao listar execuções.")
      }
      return false
    } finally {
      if (requestSeq.current === myId) setLoading(false)
    }
  }, [workflowId, filters, page])

  useEffect(() => {
    if (!active) return
    void load()
  }, [active, load])

  // Auto-refresh com:
  //  • pausa quando a aba nao esta visivel (retoma imediatamente ao voltar);
  //  • backoff exponencial em falha (base 10s → 60s), reseta apos sucesso.
  // Usa setTimeout recursivo (nao setInterval) para poder variar o delay.
  useEffect(() => {
    if (!active || !autoRefresh) return

    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | null = null
    let currentDelay = AUTO_REFRESH_BASE_MS

    const tick = async () => {
      if (cancelled) return
      if (typeof document !== "undefined" && document.visibilityState !== "visible") {
        // pausado — visibilitychange cuida de retomar
        return
      }
      const ok = await load()
      if (cancelled) return
      // Revalida visibilidade pos-await: se a aba virou hidden durante
      // o load, nao reagendamos — o listener de visibilitychange reinicia
      // quando voltar a ficar visivel.
      if (typeof document !== "undefined" && document.visibilityState !== "visible") {
        timer = null
        return
      }
      currentDelay = ok
        ? AUTO_REFRESH_BASE_MS
        : Math.min(currentDelay * 2, AUTO_REFRESH_MAX_MS)
      timer = setTimeout(tick, currentDelay)
    }

    const handleVisibility = () => {
      if (cancelled) return
      if (document.visibilityState === "visible") {
        if (timer) clearTimeout(timer)
        void tick()
      } else if (timer) {
        clearTimeout(timer)
        timer = null
      }
    }

    timer = setTimeout(tick, currentDelay)
    document.addEventListener("visibilitychange", handleVisibility)

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
      document.removeEventListener("visibilitychange", handleVisibility)
    }
  }, [active, autoRefresh, load])

  const handleFilterChange = (patch: Partial<ExecutionFilterValues>) => {
    setFilters((prev) => ({ ...prev, ...patch }))
    setPage(1)
  }

  const handleClear = () => {
    setFilters(DEFAULT_FILTERS)
    setPage(1)
  }

  const handleDeleted = (id: string) => {
    if (selectedId === id) setSelectedId(null)
    void load()
  }

  const handleCancelled = () => {
    void load()
  }

  const handleRetried = (newExecutionId: string) => {
    setSelectedId(newExecutionId)
    void load()
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <ExecutionsFilters
        values={filters}
        onChange={handleFilterChange}
        onClear={handleClear}
        onRefresh={() => void load()}
        autoRefresh={autoRefresh}
        onAutoRefreshChange={setAutoRefresh}
        loading={loading}
      />
      {error && (
        <div className="border-b border-red-500/40 bg-red-500/10 px-4 py-1.5 text-[11px] text-red-600">
          {error}
        </div>
      )}
      <div className="flex min-h-0 flex-1">
        <ExecutionsList
          items={data.items}
          loading={loading}
          selectedId={selectedId}
          onSelect={setSelectedId}
          page={page}
          size={PAGE_SIZE}
          total={data.total}
          onPageChange={setPage}
        />
        <ExecutionsDetail
          executionId={selectedId}
          workflowId={workflowId}
          onDeleted={handleDeleted}
          onCancelled={handleCancelled}
          onRetried={handleRetried}
        />
      </div>
    </div>
  )
}
