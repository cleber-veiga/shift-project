"use client"

import { useBuildMode, type PendingOp } from "@/lib/workflow/build-mode-context"
import {
  GitBranch,
  Filter,
  Database,
  Code2,
  RefreshCw,
  Layers,
  ArrowRightLeft,
  CheckCircle2,
  XCircle,
  Clock,
  Undo2,
  Trash2,
  X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { getValidSession } from "@/lib/auth"
import { useState } from "react"

// ---------------------------------------------------------------------------
// Icon map by node type
// ---------------------------------------------------------------------------

const NODE_ICONS: Record<string, React.ElementType> = {
  filter: Filter,
  if_node: GitBranch,
  sql_script: Code2,
  bulk_insert: Database,
  composite_insert: Layers,
  loop: RefreshCw,
  mapper: ArrowRightLeft,
}

function OpIcon({ nodeType }: { nodeType?: string }) {
  const Icon = (nodeType && NODE_ICONS[nodeType]) || Code2
  return <Icon className="h-3.5 w-3.5 shrink-0" />
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }: { status: PendingOp["status"] }) {
  if (status === "applied")
    return <CheckCircle2 className="h-3.5 w-3.5 text-green-500 shrink-0" />
  if (status === "failed")
    return <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
  return <Clock className="h-3.5 w-3.5 text-muted-foreground shrink-0 animate-pulse" />
}

// ---------------------------------------------------------------------------
// API helper
// ---------------------------------------------------------------------------

function getApiBaseUrl() {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL
  return value && value.trim().length > 0 ? value.trim() : "http://localhost:8000/api/v1"
}

async function authedDelete(path: string): Promise<boolean> {
  const session = await getValidSession()
  const res = await fetch(`${getApiBaseUrl()}${path}`, {
    method: "DELETE",
    headers: { Authorization: `Bearer ${session?.accessToken ?? ""}` },
  })
  return res.ok
}

// ---------------------------------------------------------------------------
// Panel
// ---------------------------------------------------------------------------

interface BuildOpsPanelProps {
  workflowId: string
  /** Optional: called when user clicks a node op row to highlight it in canvas. */
  onSelectNode?: (nodeId: string) => void
  /** The active build session id — needed for remove operations. */
  sessionId: string | null
}

export function BuildOpsPanel({ workflowId, onSelectNode, sessionId }: BuildOpsPanelProps) {
  const {
    buildState,
    pendingOps,
    canUndo,
    isUndoing,
    undoBuild,
    removePendingNode,
    removePendingEdge,
    dismissConfirmedOps,
  } = useBuildMode()
  const [removingIds, setRemovingIds] = useState<Set<string>>(new Set())

  if (buildState === "idle" && !canUndo) return null

  // O painel pode ser fechado apenas quando nao ha mais operacoes ativas
  // acontecendo — durante build ativo o usuario deve usar Cancelar/Confirmar
  // na BuildModeBar. Apos confirm (buildState=idle && canUndo=true), oferece
  // um X para dispensar sem executar undo.
  const canDismiss = buildState === "idle" && canUndo

  const nodes = pendingOps.filter((op) => op.kind === "node")
  const edges = pendingOps.filter((op) => op.kind === "edge")

  const handleRemoveNode = async (op: PendingOp) => {
    if (!sessionId || removingIds.has(op.id)) return
    setRemovingIds((prev) => new Set(prev).add(op.id))
    try {
      await authedDelete(
        `/workflows/${workflowId}/build-sessions/${sessionId}/pending-nodes/${op.id}`,
      )
      removePendingNode(op.id)
    } finally {
      setRemovingIds((prev) => {
        const next = new Set(prev)
        next.delete(op.id)
        return next
      })
    }
  }

  const handleRemoveEdge = async (op: PendingOp) => {
    if (!sessionId || removingIds.has(op.id)) return
    setRemovingIds((prev) => new Set(prev).add(op.id))
    try {
      await authedDelete(
        `/workflows/${workflowId}/build-sessions/${sessionId}/pending-edges/${op.id}`,
      )
      removePendingEdge(op.id)
    } finally {
      setRemovingIds((prev) => {
        const next = new Set(prev)
        next.delete(op.id)
        return next
      })
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-lg border bg-card p-3 text-sm shadow-md w-64">
      <div className="flex items-center justify-between gap-2">
        <span className="font-semibold text-xs uppercase tracking-wide text-muted-foreground">
          Operações propostas
        </span>
        <div className="flex items-center gap-1.5">
          <span className="text-xs text-muted-foreground">{pendingOps.length}</span>
          {canDismiss && (
            <button
              type="button"
              onClick={dismissConfirmedOps}
              className="flex items-center text-muted-foreground hover:text-foreground transition-colors"
              title="Dispensar (aplicado com sucesso)"
              aria-label="Dispensar painel"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
      </div>

      {pendingOps.length === 0 && (
        <p className="text-xs text-muted-foreground italic">Aguardando o agente...</p>
      )}

      {nodes.length > 0 && (
        <section className="space-y-1">
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Nós ({nodes.length})
          </p>
          {nodes.map((op) => (
            <div
              key={op.id}
              className={cn(
                "group flex items-center gap-2 rounded px-2 py-1",
                "bg-muted/40 hover:bg-muted/70 transition-colors",
                op.status === "pending" && onSelectNode ? "cursor-pointer" : "",
              )}
              onClick={() => {
                if (op.status === "pending" && onSelectNode) onSelectNode(op.id)
              }}
            >
              <OpIcon nodeType={op.nodeType} />
              <span className="flex-1 truncate text-xs">{op.label}</span>
              {op.status === "pending" && sessionId && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    void handleRemoveNode(op)
                  }}
                  disabled={removingIds.has(op.id)}
                  className="hidden group-hover:flex items-center text-muted-foreground hover:text-red-500 transition-colors disabled:opacity-40"
                  title="Remover operação"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              )}
              <StatusBadge status={op.status} />
            </div>
          ))}
        </section>
      )}

      {edges.length > 0 && (
        <section className="space-y-1">
          <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
            Conexões ({edges.length})
          </p>
          {edges.map((op) => (
            <div
              key={op.id}
              className={cn(
                "group flex items-center gap-2 rounded px-2 py-1",
                "bg-muted/40 hover:bg-muted/70 transition-colors",
              )}
            >
              <ArrowRightLeft className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
              <span className="flex-1 truncate text-xs font-mono">{op.label}</span>
              {op.status === "pending" && sessionId && (
                <button
                  type="button"
                  onClick={(e) => {
                    e.stopPropagation()
                    void handleRemoveEdge(op)
                  }}
                  disabled={removingIds.has(op.id)}
                  className="hidden group-hover:flex items-center text-muted-foreground hover:text-red-500 transition-colors disabled:opacity-40"
                  title="Remover conexão"
                >
                  <Trash2 className="h-3 w-3" />
                </button>
              )}
              <StatusBadge status={op.status} />
            </div>
          ))}
        </section>
      )}

      {canUndo && (
        <button
          onClick={() => undoBuild(workflowId)}
          disabled={isUndoing}
          className={cn(
            "mt-1 flex items-center justify-center gap-1.5 rounded px-2 py-1.5",
            "border border-dashed border-amber-400 text-amber-600 text-xs font-medium",
            "hover:bg-amber-50 dark:hover:bg-amber-950/30 transition-colors",
            "disabled:opacity-50 disabled:cursor-not-allowed",
          )}
        >
          <Undo2 className="h-3.5 w-3.5" />
          {isUndoing ? "Desfazendo..." : "Desfazer build"}
        </button>
      )}
    </div>
  )
}
