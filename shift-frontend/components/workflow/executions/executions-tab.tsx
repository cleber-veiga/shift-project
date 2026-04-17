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
const AUTO_REFRESH_MS = 5000

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

  const load = useCallback(async () => {
    if (workflowId === "new") {
      setData({ items: [], total: 0, page: 1, size: PAGE_SIZE })
      return
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
    } catch (e) {
      if (requestSeq.current === myId) {
        setError(e instanceof Error ? e.message : "Falha ao listar execuções.")
      }
    } finally {
      if (requestSeq.current === myId) setLoading(false)
    }
  }, [workflowId, filters, page])

  useEffect(() => {
    if (!active) return
    void load()
  }, [active, load])

  useEffect(() => {
    if (!active || !autoRefresh) return
    const id = window.setInterval(() => {
      void load()
    }, AUTO_REFRESH_MS)
    return () => window.clearInterval(id)
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
          onDeleted={handleDeleted}
          onCancelled={handleCancelled}
        />
      </div>
    </div>
  )
}
