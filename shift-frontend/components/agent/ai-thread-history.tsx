"use client"

import { useCallback, useEffect, useState } from "react"
import { MessageSquare, Trash2, X } from "lucide-react"
import { cn } from "@/lib/utils"
import type { AgentThreadSummary } from "@/lib/types/ai-panel"
import { useAIPanelContext } from "@/lib/context/ai-panel-context"
import { useAgentApi } from "@/lib/hooks/use-agent-api"
import { useDashboard } from "@/lib/context/dashboard-context"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { MorphLoader } from "@/components/ui/morph-loader"

const STATUS_LABELS: Record<string, { label: string; class: string }> = {
  running: { label: "Ativa", class: "text-primary" },
  awaiting_approval: { label: "Aguardando", class: "text-amber-500" },
  completed: { label: "Concluida", class: "text-emerald-500" },
  rejected: { label: "Rejeitada", class: "text-destructive" },
  error: { label: "Erro", class: "text-destructive" },
  expired: { label: "Expirada", class: "text-muted-foreground" },
}

function formatDate(iso: string): string {
  const d = new Date(iso)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 60) return `${minutes}min atras`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h atras`
  return d.toLocaleDateString("pt-BR", { day: "2-digit", month: "short" })
}

export function AIThreadHistory() {
  const { activeThreadId, setActiveThread, toggleHistory } = useAIPanelContext()
  const { selectedWorkspace } = useDashboard()
  const api = useAgentApi()

  const [threads, setThreads] = useState<AgentThreadSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)

  const load = useCallback(async () => {
    if (!selectedWorkspace?.id) return
    setLoading(true)
    try {
      const result = await api.listThreads(selectedWorkspace.id)
      setThreads(result.sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime()))
    } catch { /* ignora erros de listagem */ }
    finally { setLoading(false) }
  }, [selectedWorkspace?.id, api])

  useEffect(() => { void load() }, [load])

  const handleDelete = async () => {
    if (!deleteTarget) return
    setIsDeleting(true)
    try {
      await api.deleteThread(deleteTarget)
      setThreads((prev) => prev.filter((t) => t.id !== deleteTarget))
      if (activeThreadId === deleteTarget) setActiveThread(null)
    } catch { /* ignora */ }
    finally {
      setIsDeleting(false)
      setDeleteTarget(null)
    }
  }

  return (
    <>
      <div className="absolute inset-0 z-10 flex flex-col bg-background">
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-3">
          <span className="text-sm font-semibold text-foreground">Historico</span>
          <button
            type="button"
            onClick={toggleHistory}
            className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Fechar historico"
          >
            <X className="size-4" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex justify-center py-8">
              <MorphLoader className="size-5" />
            </div>
          ) : threads.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-10 text-center">
              <MessageSquare className="size-8 text-muted-foreground/30" />
              <p className="text-xs text-muted-foreground">Nenhuma conversa encontrada</p>
            </div>
          ) : (
            <div className="p-2 space-y-1">
              {threads.map((thread) => {
                const statusInfo = STATUS_LABELS[thread.status] ?? { label: thread.status, class: "text-muted-foreground" }
                const isActive = thread.id === activeThreadId

                return (
                  <div
                    key={thread.id}
                    className={cn(
                      "group flex items-start gap-2 rounded-lg p-2.5 hover:bg-accent transition-colors",
                      isActive && "bg-accent",
                    )}
                  >
                    <button
                      type="button"
                      onClick={() => {
                        setActiveThread(thread.id)
                        toggleHistory()
                      }}
                      className="flex min-w-0 flex-1 flex-col gap-0.5 text-left"
                    >
                      <span className="truncate text-xs font-medium text-foreground">
                        {thread.title ?? "Conversa sem titulo"}
                      </span>
                      <div className="flex items-center gap-1.5">
                        <span className={cn("text-[10px] font-medium", statusInfo.class)}>
                          {statusInfo.label}
                        </span>
                        <span className="text-[10px] text-muted-foreground/50">·</span>
                        <span className="text-[10px] text-muted-foreground/50">
                          {formatDate(thread.updatedAt)}
                        </span>
                      </div>
                    </button>

                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); setDeleteTarget(thread.id) }}
                      className="mt-0.5 shrink-0 opacity-0 group-hover:opacity-100 inline-flex size-6 items-center justify-center rounded-md text-muted-foreground hover:text-destructive transition"
                      aria-label="Excluir conversa"
                    >
                      <Trash2 className="size-3.5" />
                    </button>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Excluir conversa"
        description="Esta acao nao pode ser desfeita."
        confirmText="Excluir"
        confirmVariant="destructive"
        loading={isDeleting}
        onConfirm={handleDelete}
      />
    </>
  )
}
