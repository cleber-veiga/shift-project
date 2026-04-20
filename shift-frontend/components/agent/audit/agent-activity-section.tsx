"use client"

import { Activity, AlertCircle, CheckCircle2, Loader2, Search, Shield } from "lucide-react"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useDashboard } from "@/lib/context/dashboard-context"
import {
  useAgentAudit,
  type AuditEntry,
  type AuditEntryDetail,
  type AuditStats,
} from "@/lib/hooks/use-agent-audit"
import type { DashboardScope } from "@/lib/dashboard-navigation"

interface AgentActivitySectionProps {
  scope: DashboardScope
}

function formatTimestamp(iso: string): string {
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso))
  } catch {
    return iso
  }
}

function DetailDrawer({
  entry,
  onClose,
}: {
  entry: AuditEntryDetail | null
  onClose: () => void
}) {
  if (!entry) return null
  const warnings = (entry.log_metadata?.sanitizer_warnings ?? []) as string[]
  return (
    <div className="fixed inset-0 z-50 flex">
      <button
        type="button"
        onClick={onClose}
        className="flex-1 bg-black/30"
        aria-label="Fechar detalhe"
      />
      <aside className="relative flex h-full w-full max-w-xl flex-col gap-4 overflow-auto bg-card p-6 shadow-xl">
        <header className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-lg font-semibold text-foreground">{entry.tool_name}</h3>
            <p className="text-xs text-muted-foreground">
              {formatTimestamp(entry.created_at)} · {entry.duration_ms ?? "—"} ms
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border bg-background px-2 py-1 text-xs text-muted-foreground hover:bg-accent"
          >
            Fechar
          </button>
        </header>

        <section className="space-y-1 text-xs">
          <p className="font-semibold uppercase tracking-wide text-muted-foreground">Status</p>
          <span
            className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium ${
              entry.status === "success"
                ? "bg-emerald-500/10 text-emerald-600"
                : "bg-destructive/10 text-destructive"
            }`}
          >
            {entry.status === "success" ? (
              <CheckCircle2 className="size-3" />
            ) : (
              <AlertCircle className="size-3" />
            )}
            {entry.status.toUpperCase()}
          </span>
          {entry.error_message ? (
            <pre className="mt-2 whitespace-pre-wrap break-all rounded-md bg-destructive/5 p-2 text-[11px] text-destructive">
              {entry.error_message}
            </pre>
          ) : null}
        </section>

        <section className="space-y-1 text-xs">
          <p className="font-semibold uppercase tracking-wide text-muted-foreground">Argumentos</p>
          <pre className="max-h-48 overflow-auto rounded-md border border-border bg-background p-2 text-[11px] text-foreground">
            {JSON.stringify(entry.tool_arguments, null, 2)}
          </pre>
        </section>

        {warnings.length > 0 ? (
          <section className="space-y-1 text-xs">
            <p className="flex items-center gap-1 font-semibold uppercase tracking-wide text-amber-600">
              <Shield className="size-3.5" /> Avisos do sanitizer
            </p>
            <ul className="list-disc space-y-1 pl-5 text-[11px] text-amber-700">
              {warnings.map((warning, i) => (
                <li key={i}>{warning}</li>
              ))}
            </ul>
          </section>
        ) : null}

        <section className="space-y-1 text-xs">
          <p className="font-semibold uppercase tracking-wide text-muted-foreground">
            Preview do resultado (raw)
          </p>
          <pre className="max-h-72 overflow-auto rounded-md border border-border bg-background p-2 text-[11px] text-foreground">
            {entry.tool_result_preview ?? "(vazio)"}
          </pre>
        </section>

        <section className="space-y-1 text-xs">
          <p className="font-semibold uppercase tracking-wide text-muted-foreground">IDs</p>
          <p className="font-mono text-[11px] text-muted-foreground">thread {entry.thread_id}</p>
          <p className="font-mono text-[11px] text-muted-foreground">user {entry.user_id}</p>
          {entry.approval_id ? (
            <p className="font-mono text-[11px] text-muted-foreground">
              approval {entry.approval_id}
            </p>
          ) : null}
        </section>
      </aside>
    </div>
  )
}

export function AgentActivitySection({ scope }: AgentActivitySectionProps) {
  const { selectedWorkspace, selectedProject } = useDashboard()
  const workspaceId = selectedWorkspace?.id ?? null
  const projectId = scope === "project" ? selectedProject?.id ?? null : null
  const { list, stats, getEntry } = useAgentAudit()

  const [entries, setEntries] = useState<AuditEntry[]>([])
  const [statsData, setStatsData] = useState<AuditStats | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [toolFilter, setToolFilter] = useState("")
  const [statusFilter, setStatusFilter] = useState<"all" | "success" | "error">("all")
  const [detail, setDetail] = useState<AuditEntryDetail | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)

  const load = useCallback(async () => {
    if (!workspaceId) return
    setLoading(true)
    setError(null)
    try {
      const [listData, statsResponse] = await Promise.all([
        list({
          workspaceId,
          projectId,
          toolName: toolFilter.trim() || null,
          status: statusFilter === "all" ? null : statusFilter,
          limit: 100,
        }),
        stats(workspaceId, projectId, 30),
      ])
      setEntries(listData.items)
      setStatsData(statsResponse)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro desconhecido.")
      setEntries([])
      setStatsData(null)
    } finally {
      setLoading(false)
    }
  }, [list, stats, workspaceId, projectId, toolFilter, statusFilter])

  useEffect(() => {
    load()
  }, [load])

  const openDetail = async (id: string) => {
    if (!workspaceId) return
    setDetailLoading(true)
    try {
      const entry = await getEntry(id, workspaceId)
      setDetail(entry)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar detalhe.")
    } finally {
      setDetailLoading(false)
    }
  }

  const summary = useMemo(() => {
    if (!statsData) return null
    const pct = Math.round(statsData.success_rate * 100)
    return { pct, total: statsData.total_executions, failed: statsData.failed_executions }
  }, [statsData])

  if (!workspaceId) {
    return (
      <div className="rounded-2xl border border-dashed border-border bg-card/60 p-6 text-center text-sm text-muted-foreground">
        Selecione um workspace para visualizar a atividade do agente.
      </div>
    )
  }

  return (
    <section className="space-y-5">
      <header className="space-y-2">
        <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          <Activity className="size-3.5" /> Agent Activity
        </div>
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">Atividade do Agente</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Registro imutavel de ferramentas executadas pelo Platform Agent, com
            avisos de seguranca (sanitizer) e rastreabilidade por aprovacao.
          </p>
        </div>
      </header>

      {summary ? (
        <div className="grid gap-3 sm:grid-cols-3">
          <article className="rounded-xl border border-border bg-card p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Execucoes (30d)
            </p>
            <p className="mt-1 text-2xl font-semibold text-foreground">{summary.total}</p>
          </article>
          <article className="rounded-xl border border-border bg-card p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Taxa de sucesso
            </p>
            <p className="mt-1 text-2xl font-semibold text-foreground">{summary.pct}%</p>
          </article>
          <article className="rounded-xl border border-border bg-card p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Falhas
            </p>
            <p className="mt-1 text-2xl font-semibold text-foreground">{summary.failed}</p>
          </article>
        </div>
      ) : null}

      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 sm:flex-row sm:items-center">
        <label className="flex h-9 flex-1 items-center gap-2 rounded-md border border-input bg-background px-3">
          <Search className="size-4 text-muted-foreground" />
          <input
            type="text"
            value={toolFilter}
            onChange={(e) => setToolFilter(e.target.value)}
            placeholder="Filtrar por tool (ex: execute_workflow)"
            className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
          />
        </label>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value as typeof statusFilter)}
          className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none"
        >
          <option value="all">Todos os status</option>
          <option value="success">Sucesso</option>
          <option value="error">Erro</option>
        </select>
      </div>

      {error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Carregando auditoria...
        </div>
      ) : entries.length === 0 ? (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border bg-card">
          <p className="text-sm text-muted-foreground">Nenhuma execucao registrada.</p>
        </div>
      ) : (
        <div className="overflow-auto rounded-xl border border-border bg-card shadow-sm">
          <div className="grid min-w-[720px] grid-cols-[1fr_110px_120px_160px_90px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Tool / Thread</span>
            <span>Status</span>
            <span>Duracao</span>
            <span>Quando</span>
            <span className="text-right">Detalhe</span>
          </div>
          <div className="divide-y divide-border">
            {entries.map((row) => (
              <div
                key={row.id}
                className="grid min-w-[720px] grid-cols-[1fr_110px_120px_160px_90px] items-center px-4 py-3 text-[12px] hover:bg-muted/10"
              >
                <div className="min-w-0">
                  <p className="truncate font-semibold text-foreground">{row.tool_name}</p>
                  <p className="truncate font-mono text-[10px] text-muted-foreground">
                    thread {row.thread_id.slice(0, 8)}…
                  </p>
                </div>
                <span
                  className={`inline-flex w-fit items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium ${
                    row.status === "success"
                      ? "bg-emerald-500/10 text-emerald-600"
                      : "bg-destructive/10 text-destructive"
                  }`}
                >
                  {row.status === "success" ? (
                    <CheckCircle2 className="size-3" />
                  ) : (
                    <AlertCircle className="size-3" />
                  )}
                  {row.status.toUpperCase()}
                </span>
                <span className="text-muted-foreground">{row.duration_ms ?? "—"} ms</span>
                <span className="text-muted-foreground">{formatTimestamp(row.created_at)}</span>
                <div className="text-right">
                  <button
                    type="button"
                    onClick={() => openDetail(row.id)}
                    disabled={detailLoading}
                    className="rounded-md border border-border bg-background px-2 py-1 text-[11px] font-medium text-foreground hover:bg-accent disabled:opacity-50"
                  >
                    Ver
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <DetailDrawer entry={detail} onClose={() => setDetail(null)} />
    </section>
  )
}
