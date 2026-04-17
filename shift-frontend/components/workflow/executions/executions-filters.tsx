"use client"

import { RefreshCw, Eraser } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ExecutionStatus, TriggeredBy } from "@/lib/api/executions"

export interface ExecutionFilterValues {
  status: ExecutionStatus | ""
  triggered_by: TriggeredBy | ""
  from: string
  to: string
}

interface ExecutionsFiltersProps {
  values: ExecutionFilterValues
  onChange: (patch: Partial<ExecutionFilterValues>) => void
  onClear: () => void
  onRefresh: () => void
  autoRefresh: boolean
  onAutoRefreshChange: (next: boolean) => void
  loading: boolean
}

const STATUS_OPTIONS: { value: ExecutionStatus | ""; label: string }[] = [
  { value: "", label: "Status: todos" },
  { value: "PENDING", label: "PENDING" },
  { value: "RUNNING", label: "RUNNING" },
  { value: "SUCCESS", label: "SUCCESS" },
  { value: "FAILED", label: "FAILED" },
  { value: "CANCELLED", label: "CANCELLED" },
  { value: "ABORTED", label: "ABORTED" },
  { value: "CRASHED", label: "CRASHED" },
]

const TRIGGER_OPTIONS: { value: TriggeredBy | ""; label: string }[] = [
  { value: "", label: "Origem: todas" },
  { value: "manual", label: "Manual (UI)" },
  { value: "cron", label: "Cron" },
  { value: "api", label: "API" },
  { value: "webhook", label: "Webhook" },
]

export function ExecutionsFilters({
  values,
  onChange,
  onClear,
  onRefresh,
  autoRefresh,
  onAutoRefreshChange,
  loading,
}: ExecutionsFiltersProps) {
  const selectCls =
    "h-8 rounded border border-border bg-card px-2 text-xs text-foreground outline-none focus:border-ring"
  const dateCls =
    "h-8 rounded border border-border bg-card px-2 text-xs text-foreground outline-none focus:border-ring"

  return (
    <div className="flex flex-wrap items-center gap-2 border-b border-border bg-muted/30 px-4 py-2">
      <select
        className={selectCls}
        value={values.status}
        onChange={(e) =>
          onChange({ status: (e.target.value as ExecutionStatus) || "" })
        }
      >
        {STATUS_OPTIONS.map((opt) => (
          <option key={opt.value || "all"} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <select
        className={selectCls}
        value={values.triggered_by}
        onChange={(e) =>
          onChange({ triggered_by: (e.target.value as TriggeredBy) || "" })
        }
      >
        {TRIGGER_OPTIONS.map((opt) => (
          <option key={opt.value || "all"} value={opt.value}>
            {opt.label}
          </option>
        ))}
      </select>

      <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
        De
        <input
          type="datetime-local"
          className={dateCls}
          value={values.from}
          onChange={(e) => onChange({ from: e.target.value })}
        />
      </label>
      <label className="flex items-center gap-1 text-[11px] text-muted-foreground">
        Até
        <input
          type="datetime-local"
          className={dateCls}
          value={values.to}
          onChange={(e) => onChange({ to: e.target.value })}
        />
      </label>

      <button
        type="button"
        onClick={onClear}
        className="flex h-8 items-center gap-1 rounded border border-border bg-card px-2 text-xs text-muted-foreground hover:text-foreground"
      >
        <Eraser className="size-3.5" />
        Limpar
      </button>

      <button
        type="button"
        onClick={onRefresh}
        disabled={loading}
        className="flex h-8 items-center gap-1 rounded border border-border bg-card px-2 text-xs text-foreground hover:bg-muted disabled:opacity-60"
      >
        <RefreshCw className={cn("size-3.5", loading && "animate-spin")} />
        Atualizar
      </button>

      <label className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
        <input
          type="checkbox"
          checked={autoRefresh}
          onChange={(e) => onAutoRefreshChange(e.target.checked)}
          className="size-3.5"
        />
        Auto refresh (5s)
      </label>
    </div>
  )
}
