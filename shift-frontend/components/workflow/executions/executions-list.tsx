"use client"

import {
  Camera,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock,
  DatabaseZap,
  Loader2,
  Square,
  User,
  Webhook,
  XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { formatDuration, formatRelative } from "@/lib/format"
import type {
  ExecutionStatus,
  ExecutionSummary,
  TriggeredBy,
} from "@/lib/api/executions"

interface ExecutionsListProps {
  items: ExecutionSummary[]
  loading: boolean
  selectedId: string | null
  onSelect: (id: string) => void
  page: number
  size: number
  total: number
  onPageChange: (page: number) => void
}

function statusIcon(status: ExecutionStatus) {
  switch (status) {
    case "COMPLETED":
    case "SUCCESS":
      return <CheckCircle2 className="size-4 text-emerald-500" />
    case "FAILED":
    case "CRASHED":
      return <XCircle className="size-4 text-red-500" />
    case "RUNNING":
      return <Loader2 className="size-4 animate-spin text-blue-500" />
    case "PENDING":
      return <Loader2 className="size-4 text-amber-500" />
    case "CANCELLED":
    case "ABORTED":
      return <Square className="size-4 text-zinc-500" />
    default:
      return <Square className="size-4 text-zinc-500" />
  }
}

function triggerIcon(trigger: TriggeredBy) {
  switch (trigger) {
    case "cron":
      return <Clock className="size-3.5" />
    case "manual":
      return <User className="size-3.5" />
    case "api":
      return <DatabaseZap className="size-3.5" />
    case "webhook":
      return <Webhook className="size-3.5" />
    default:
      return null
  }
}

export function ExecutionsList({
  items,
  loading,
  selectedId,
  onSelect,
  page,
  size,
  total,
  onPageChange,
}: ExecutionsListProps) {
  const totalPages = Math.max(1, Math.ceil(total / size))

  return (
    <div className="flex w-[360px] min-w-[280px] shrink-0 flex-col border-r border-border">
      <div className="min-h-0 flex-1 overflow-auto">
        {loading && items.length === 0 && (
          <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
            <Loader2 className="mr-2 size-4 animate-spin" />
            Carregando execuções…
          </div>
        )}
        {!loading && items.length === 0 && (
          <div className="flex h-full flex-col items-center justify-center gap-1 p-6 text-center text-xs text-muted-foreground">
            <span>Nenhuma execução encontrada.</span>
            <span className="text-[11px] opacity-70">
              Rode o workflow ou ajuste os filtros.
            </span>
          </div>
        )}
        <ul className="divide-y divide-border">
          {items.map((item) => {
            const selected = item.id === selectedId
            return (
              <li key={item.id}>
                <button
                  type="button"
                  onClick={() => onSelect(item.id)}
                  className={cn(
                    "flex w-full flex-col gap-1 px-3 py-2 text-left transition-colors",
                    selected ? "bg-accent" : "hover:bg-muted/60",
                  )}
                >
                  <div className="flex items-center gap-2 text-xs">
                    {statusIcon(item.status)}
                    <span className="font-medium text-foreground">
                      {item.status}
                    </span>
                    <span className="ml-auto flex items-center gap-1 text-[11px] text-muted-foreground">
                      {triggerIcon(item.triggered_by)}
                      {item.triggered_by}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                    <span>{formatRelative(item.started_at)}</span>
                    <span className="opacity-60">•</span>
                    <span>{formatDuration(item.duration_ms)}</span>
                    <span className="opacity-60">•</span>
                    <span>{item.node_count} nós</span>
                    {item.template_version && (
                      <span
                        title="Snapshot da definição disponível"
                        className="ml-auto flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] text-indigo-500 bg-indigo-500/10"
                      >
                        <Camera className="size-2.5" />
                        snap
                      </span>
                    )}
                  </div>
                  {item.error_message && (
                    <div className="truncate text-[11px] text-red-500/90">
                      {item.error_message}
                    </div>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      </div>

      <div className="flex shrink-0 items-center justify-between border-t border-border bg-muted/30 px-3 py-1.5 text-[11px] text-muted-foreground">
        <span>
          {total === 0 ? "0" : `Page ${page} of ${totalPages}`}
          <span className="ml-2 opacity-70">({total} total)</span>
        </span>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={() => onPageChange(Math.max(1, page - 1))}
            disabled={page <= 1 || loading}
            className="flex size-6 items-center justify-center rounded hover:bg-muted disabled:opacity-40"
            aria-label="Página anterior"
          >
            <ChevronLeft className="size-3.5" />
          </button>
          <button
            type="button"
            onClick={() => onPageChange(Math.min(totalPages, page + 1))}
            disabled={page >= totalPages || loading}
            className="flex size-6 items-center justify-center rounded hover:bg-muted disabled:opacity-40"
            aria-label="Próxima página"
          >
            <ChevronRight className="size-3.5" />
          </button>
        </div>
      </div>
    </div>
  )
}
