"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { AlertTriangle, CheckCircle2, Loader2, RefreshCw, Search } from "lucide-react"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useToast } from "@/lib/context/toast-context"
import { hasWorkspacePermission } from "@/lib/permissions"
import {
  type DeadLetterItem,
  listDeadLetters,
  retryDeadLetter,
} from "@/lib/api/dead-letters"

function formatDateTime(iso: string): string {
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

function formatPayload(payload: Record<string, unknown>): string {
  try {
    return JSON.stringify(payload, null, 2)
  } catch {
    return String(payload)
  }
}

export function DeadLettersSection() {
  const { selectedWorkspace } = useDashboard()
  const toast = useToast()

  const wsRole = selectedWorkspace?.my_role ?? null
  const canRetry = hasWorkspacePermission(wsRole, "CONSULTANT")

  const [items, setItems] = useState<DeadLetterItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")
  const [search, setSearch] = useState("")
  const [includeResolved, setIncludeResolved] = useState(false)
  const [retryingId, setRetryingId] = useState<string | null>(null)
  const [expandedId, setExpandedId] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!selectedWorkspace?.id) return
    setLoading(true)
    setError("")
    try {
      const res = await listDeadLetters({
        workspaceId: selectedWorkspace.id,
        includeResolved,
        size: 200,
      })
      setItems(res.items)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar dead-letters.")
      setItems([])
    } finally {
      setLoading(false)
    }
  }, [selectedWorkspace?.id, includeResolved])

  useEffect(() => {
    void load()
  }, [load])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter(
      (item) =>
        item.node_id.toLowerCase().includes(q) ||
        item.error_message.toLowerCase().includes(q) ||
        item.execution_id.toLowerCase().includes(q),
    )
  }, [items, search])

  async function handleRetry(id: string) {
    setRetryingId(id)
    try {
      const res = await retryDeadLetter(id)
      if (res.resolved) {
        toast.success("Retry bem-sucedido", "Dead-letter reprocessado.")
      } else {
        toast.error("Retry falhou", res.message ?? "Verifique os detalhes.")
      }
      await load()
    } catch (err) {
      toast.error("Erro ao reprocessar", err instanceof Error ? err.message : "")
    } finally {
      setRetryingId(null)
    }
  }

  if (!selectedWorkspace) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border bg-card/60 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          Selecione um workspace para visualizar dead-letters.
        </p>
      </div>
    )
  }

  return (
    <section className="space-y-4">
      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-2 sm:flex-row sm:items-center sm:justify-between">
        <label className="flex h-8 w-full items-center gap-1.5 rounded-md border border-input bg-background px-2.5 sm:w-[240px]">
          <Search className="size-3 text-muted-foreground" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Buscar por nó, erro ou execução…"
            className="w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
          />
        </label>

        <div className="flex flex-wrap items-center gap-1.5">
          <label className="inline-flex items-center gap-2 text-xs font-medium text-muted-foreground">
            <input
              type="checkbox"
              checked={includeResolved}
              onChange={(e) => setIncludeResolved(e.target.checked)}
              className="size-3.5 rounded border-input"
            />
            Mostrar resolvidos
          </label>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex h-8 items-center justify-center gap-1 rounded-md border border-border bg-background px-2.5 text-xs font-medium text-foreground transition hover:bg-accent"
          >
            <RefreshCw className="size-3.5" />
            Atualizar
          </button>
        </div>
      </div>

      {error ? (
        <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {loading ? (
        <div className="flex h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Carregando dead-letters…
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex h-40 flex-col items-center justify-center gap-2 rounded-xl border border-dashed border-border bg-card/60">
          <AlertTriangle className="size-6 text-muted-foreground" />
          <p className="text-sm text-muted-foreground">
            {items.length === 0
              ? "Nenhuma entrada em dead-letter."
              : "Nenhum resultado para a busca."}
          </p>
        </div>
      ) : (
        <div className="overflow-auto rounded-xl border border-border bg-card shadow-sm">
          <div className="grid min-w-[960px] grid-cols-[180px_1fr_240px_140px_140px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Nó</span>
            <span>Erro</span>
            <span>Execução</span>
            <span>Capturado em</span>
            <span className="text-right">Ações</span>
          </div>

          <div className="divide-y divide-border">
            {filtered.map((item) => {
              const isExpanded = expandedId === item.id
              const isRetrying = retryingId === item.id
              return (
                <div key={item.id}>
                  <div className="grid min-w-[960px] grid-cols-[180px_1fr_240px_140px_140px] items-center px-4 py-3 transition-colors hover:bg-muted/10">
                    <div className="flex items-center gap-2">
                      {item.resolved_at ? (
                        <CheckCircle2 className="size-4 text-emerald-500" />
                      ) : (
                        <AlertTriangle className="size-4 text-red-500" />
                      )}
                      <span className="truncate text-[13px] font-medium text-foreground">
                        {item.node_id}
                      </span>
                    </div>

                    <p className="truncate pr-3 text-[12px] text-foreground" title={item.error_message}>
                      {item.error_message}
                    </p>

                    <p className="truncate font-mono text-[11px] text-muted-foreground" title={item.execution_id}>
                      {item.execution_id.slice(0, 8)}…
                    </p>

                    <p className="text-[12px] text-foreground">
                      {formatDateTime(item.created_at)}
                    </p>

                    <div className="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => setExpandedId(isExpanded ? null : item.id)}
                        className="rounded px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                      >
                        {isExpanded ? "Ocultar" : "Payload"}
                      </button>
                      {canRetry && !item.resolved_at ? (
                        <button
                          type="button"
                          disabled={isRetrying}
                          onClick={() => void handleRetry(item.id)}
                          className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-1 text-[11px] font-medium text-primary transition-colors hover:bg-primary/20 disabled:opacity-50"
                        >
                          {isRetrying ? (
                            <Loader2 className="size-3 animate-spin" />
                          ) : (
                            <RefreshCw className="size-3" />
                          )}
                          Retry
                        </button>
                      ) : null}
                    </div>
                  </div>

                  {isExpanded ? (
                    <div className="grid min-w-[960px] gap-3 bg-muted/30 px-4 py-3 text-[11px]">
                      <div>
                        <span className="font-semibold uppercase tracking-wide text-muted-foreground">
                          Tentativas: {item.retry_count}
                        </span>
                        {item.resolved_at ? (
                          <span className="ml-3 font-semibold uppercase tracking-wide text-emerald-600">
                            Resolvido em {formatDateTime(item.resolved_at)}
                          </span>
                        ) : null}
                      </div>
                      <pre className="overflow-auto rounded-md border border-border bg-background p-3 font-mono text-[11px] text-foreground">
                        {formatPayload(item.payload)}
                      </pre>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}
