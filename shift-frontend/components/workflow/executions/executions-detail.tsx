"use client"

import { useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  Copy,
  DatabaseZap,
  GitCompareArrows,
  Loader2,
  Play,
  Sparkles,
  Square,
  Trash2,
  User,
  Webhook,
  XCircle,
  Zap,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { formatDateTime, formatDuration } from "@/lib/format"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import {
  cancelExecution,
  deleteExecution,
  getExecutionDetail,
  type ExecutionDetail,
  type ExecutionStatus,
  type NodeExecution,
  type TriggeredBy,
} from "@/lib/api/executions"
import { SnapshotCanvasModal } from "@/components/workflow/executions/snapshot-canvas-modal"
import { executeWorkflow } from "@/lib/api/workflow-variables"

interface ExecutionsDetailProps {
  executionId: string | null
  workflowId: string
  onDeleted: (id: string) => void
  onCancelled: (id: string) => void
  onRetried?: (newExecutionId: string) => void
}

function statusBadgeCls(status: ExecutionStatus) {
  switch (status) {
    case "COMPLETED":
    case "SUCCESS":
      return "bg-emerald-500/15 text-emerald-600"
    case "FAILED":
    case "CRASHED":
      return "bg-red-500/15 text-red-600"
    case "RUNNING":
      return "bg-blue-500/15 text-blue-600"
    case "PENDING":
      return "bg-amber-500/15 text-amber-600"
    case "CANCELLED":
    case "ABORTED":
      return "bg-zinc-500/15 text-zinc-600"
    default:
      return "bg-muted text-muted-foreground"
  }
}

function triggerLabel(trigger: TriggeredBy) {
  switch (trigger) {
    case "cron":
      return (
        <span className="inline-flex items-center gap-1">
          <Clock className="size-3.5" /> cron
        </span>
      )
    case "manual":
      return (
        <span className="inline-flex items-center gap-1">
          <User className="size-3.5" /> manual
        </span>
      )
    case "api":
      return (
        <span className="inline-flex items-center gap-1">
          <DatabaseZap className="size-3.5" /> api
        </span>
      )
    case "webhook":
      return (
        <span className="inline-flex items-center gap-1">
          <Webhook className="size-3.5" /> webhook
        </span>
      )
    default:
      return <span>{trigger}</span>
  }
}

function nodeStatusIcon(status: NodeExecution["status"]) {
  switch (status) {
    case "success":
      return <CheckCircle2 className="size-3.5 text-emerald-500" />
    case "error":
      return <XCircle className="size-3.5 text-red-500" />
    case "running":
      return <Loader2 className="size-3.5 animate-spin text-blue-500" />
    case "skipped":
      return <Square className="size-3.5 text-zinc-400" />
    default:
      return <Square className="size-3.5 text-zinc-400" />
  }
}

export function ExecutionsDetail({
  executionId,
  workflowId,
  onDeleted,
  onCancelled,
  onRetried,
}: ExecutionsDetailProps) {
  const [detail, setDetail] = useState<ExecutionDetail | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [showSnapshot, setShowSnapshot] = useState(false)

  useEffect(() => {
    if (!executionId) {
      setDetail(null)
      setError(null)
      return
    }
    let cancelled = false
    setLoading(true)
    setError(null)
    getExecutionDetail(executionId)
      .then((d) => {
        if (!cancelled) setDetail(d)
      })
      .catch((e: unknown) => {
        if (!cancelled)
          setError(e instanceof Error ? e.message : "Falha ao carregar execução.")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [executionId])

  const sortedNodes = useMemo(() => {
    if (!detail) return []
    return [...detail.nodes].sort((a, b) => {
      const ta = a.started_at ? Date.parse(a.started_at) : 0
      const tb = b.started_at ? Date.parse(b.started_at) : 0
      if (ta !== tb) return ta - tb
      return a.node_id.localeCompare(b.node_id)
    })
  }, [detail])

  const handleCopyId = async () => {
    if (!detail) return
    try {
      await navigator.clipboard.writeText(detail.execution_id)
    } catch {
      // Clipboard indisponivel — silencioso.
    }
  }

  const handleCancel = async () => {
    if (!detail) return
    if (!window.confirm("Cancelar esta execução em andamento?")) return
    setBusy(true)
    try {
      await cancelExecution(detail.execution_id)
      onCancelled(detail.execution_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao cancelar execução.")
    } finally {
      setBusy(false)
    }
  }

  const handleDelete = async () => {
    if (!detail) return
    if (!window.confirm("Excluir esta execução do histórico?")) return
    setBusy(true)
    try {
      await deleteExecution(detail.execution_id)
      onDeleted(detail.execution_id)
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao excluir execução.")
    } finally {
      setBusy(false)
    }
  }

  const handleRetry = async () => {
    if (!detail) return
    const reusePrevVars =
      !!detail.input_data?.variable_values &&
      Object.keys(detail.input_data.variable_values).length > 0
    const message = reusePrevVars
      ? "Retomar execução? Nós concluídos serão pulados via checkpoint e as mesmas variáveis serão reutilizadas."
      : "Retomar execução? Nós concluídos serão pulados via checkpoint."
    if (!window.confirm(message)) return
    setBusy(true)
    try {
      const variableValues = (detail.input_data?.variable_values ?? {}) as Record<
        string,
        unknown
      >
      const resp = await executeWorkflow(workflowId, {
        variableValues,
        retryFromExecutionId: detail.execution_id,
      })
      if ("execution_id" in resp) {
        onRetried?.(resp.execution_id)
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Falha ao retomar execução.")
    } finally {
      setBusy(false)
    }
  }

  if (!executionId) {
    return (
      <div className="flex flex-1 items-center justify-center text-xs text-muted-foreground">
        Selecione uma execução para inspecionar.
      </div>
    )
  }

  if (loading && !detail) {
    return (
      <div className="flex flex-1 items-center justify-center text-xs text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        Carregando…
      </div>
    )
  }

  if (error && !detail) {
    return (
      <div className="flex flex-1 items-center justify-center p-4 text-xs text-red-500">
        {error}
      </div>
    )
  }

  if (!detail) return null

  const durationMs =
    detail.started_at && detail.completed_at
      ? Date.parse(detail.completed_at) - Date.parse(detail.started_at)
      : null

  return (
    <>
    {showSnapshot && detail && (
      <SnapshotCanvasModal
        executionId={detail.execution_id}
        onClose={() => setShowSnapshot(false)}
      />
    )}
    <div className="flex min-w-0 flex-1 flex-col">
      <div className="shrink-0 border-b border-border bg-muted/20 px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <span
            className={cn(
              "rounded px-2 py-0.5 text-[11px] font-semibold",
              statusBadgeCls(detail.status),
            )}
          >
            {detail.status}
          </span>
          <span className="text-[11px] text-muted-foreground">
            {triggerLabel(detail.triggered_by)}
          </span>
          <span className="text-[11px] text-muted-foreground">
            {formatDateTime(detail.started_at)}
          </span>
          <span className="text-[11px] text-muted-foreground">
            • {formatDuration(durationMs)}
          </span>
          <button
            type="button"
            onClick={handleCopyId}
            className="ml-auto flex items-center gap-1 rounded border border-border bg-card px-2 py-0.5 font-mono text-[11px] text-muted-foreground hover:text-foreground"
            title={detail.execution_id}
          >
            <Copy className="size-3" />
            {detail.execution_id.slice(0, 8)}
          </button>
          {/* Ver snapshot — disponivel para qualquer execucao com snapshot */}
          {detail.definition_snapshot_hash && (
            <button
              type="button"
              onClick={() => setShowSnapshot(true)}
              className="flex items-center gap-1 rounded border border-border bg-card px-2 py-0.5 text-[11px] text-indigo-600 hover:bg-indigo-500/10"
              title="Ver o workflow como estava no momento desta execução"
            >
              <GitCompareArrows className="size-3" />
              Ver como foi executado
            </button>
          )}

          {detail.status === "RUNNING" ? (
            <button
              type="button"
              onClick={handleCancel}
              disabled={busy}
              className="flex items-center gap-1 rounded border border-border bg-card px-2 py-0.5 text-[11px] text-amber-600 hover:bg-amber-500/10 disabled:opacity-60"
            >
              Cancelar
            </button>
          ) : (
            <>
              {(detail.status === "FAILED" ||
                detail.status === "CRASHED" ||
                detail.status === "CANCELLED" ||
                detail.status === "ABORTED") && (
                <button
                  type="button"
                  onClick={handleRetry}
                  disabled={busy}
                  title="Retomar a partir dos checkpoints salvos desta execução."
                  className="flex items-center gap-1 rounded border border-border bg-card px-2 py-0.5 text-[11px] text-emerald-600 hover:bg-emerald-500/10 disabled:opacity-60"
                >
                  <Play className="size-3" />
                  Retomar
                </button>
              )}
              <button
                type="button"
                onClick={handleDelete}
                disabled={busy}
                className="flex items-center gap-1 rounded border border-border bg-card px-2 py-0.5 text-[11px] text-red-600 hover:bg-red-500/10 disabled:opacity-60"
              >
                <Trash2 className="size-3" />
                Excluir
              </button>
            </>
          )}
        </div>
      </div>

      {detail.error_message && (
        <div className="m-3 flex items-start gap-2 rounded border border-red-500/40 bg-red-500/10 p-3 text-[11px] text-red-600">
          <AlertTriangle className="size-4 shrink-0" />
          <pre className="whitespace-pre-wrap break-all font-mono">
            {detail.error_message}
          </pre>
        </div>
      )}

      {detail.input_data?.variable_values &&
        Object.keys(detail.input_data.variable_values).length > 0 && (
          <div className="mx-3 mt-3 rounded border border-violet-500/20 bg-violet-500/5 p-3">
            <p className="mb-2 text-[10px] font-semibold uppercase tracking-wider text-violet-600 dark:text-violet-400">
              Variáveis usadas
            </p>
            <dl className="space-y-1">
              {Object.entries(detail.input_data.variable_values).map(([k, v]) => (
                <div key={k} className="flex items-baseline gap-2 text-[11px]">
                  <dt className="shrink-0 font-mono text-muted-foreground">{`{{vars.${k}}}`}</dt>
                  <dd className="truncate font-mono text-foreground">
                    {v === "***" ? (
                      <span className="text-muted-foreground">••••••</span>
                    ) : (
                      String(v)
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}

      <div className="min-h-0 flex-1 overflow-auto p-3">
        {sortedNodes.length === 0 ? (
          <div className="text-center text-xs text-muted-foreground">
            Nenhum nó executado nesta run.
          </div>
        ) : (
          <ul className="space-y-2">
            {sortedNodes.map((node) => {
              const Icon = getNodeIcon(node.node_type)
              const isOpen = !!expanded[node.id]
              const displayLabel = node.label ?? node.node_id
              return (
                <li
                  key={node.id}
                  className="rounded border border-border bg-card"
                >
                  <button
                    type="button"
                    onClick={() =>
                      setExpanded((prev) => ({ ...prev, [node.id]: !prev[node.id] }))
                    }
                    className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/40"
                  >
                    {isOpen ? (
                      <ChevronDown className="size-3.5 text-muted-foreground" />
                    ) : (
                      <ChevronRight className="size-3.5 text-muted-foreground" />
                    )}
                    <Icon className="size-3.5 text-muted-foreground" />
                    {nodeStatusIcon(node.status)}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs font-medium text-foreground">
                        {displayLabel}
                      </div>
                      <div className="truncate text-[11px] text-muted-foreground">
                        {node.node_type}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 text-[11px] text-muted-foreground">
                      {node.is_cache_hit && (
                        <span
                          title="Resultado servido pelo cache de extração"
                          className="flex items-center gap-0.5 rounded px-1 py-0.5 text-[10px] font-medium text-emerald-600 bg-emerald-500/10"
                        >
                          <Zap className="size-2.5" />
                          cache hit
                        </span>
                      )}
                      <span>{formatDuration(node.duration_ms)}</span>
                      {node.row_count_out != null && (
                        <span>• {node.row_count_out} linhas</span>
                      )}
                    </div>
                  </button>
                  {isOpen && (
                    <div className="space-y-2 border-t border-border px-3 py-2">
                      {node.error_message && (
                        <pre className="whitespace-pre-wrap break-all rounded bg-red-500/10 p-2 font-mono text-[11px] text-red-600">
                          {node.error_message}
                        </pre>
                      )}
                      {node.output_summary ? (
                        <pre className="whitespace-pre-wrap break-all rounded bg-muted/40 p-2 font-mono text-[11px] text-foreground">
                          {JSON.stringify(node.output_summary, null, 2)}
                        </pre>
                      ) : (
                        !node.error_message && (
                          <div className="text-[11px] text-muted-foreground">
                            Sem output_summary disponível.
                          </div>
                        )
                      )}
                    </div>
                  )}
                </li>
              )
            })}
          </ul>
        )}
      </div>
    </div>
    </>
  )
}
