"use client"

import { useEffect, useRef, useState } from "react"
import { AlertTriangle, CheckCircle2, DatabaseZap, Loader2, Square, X, XCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { getNodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import type { WorkflowTestEvent } from "@/lib/auth"
import { DataViewer } from "@/components/workflow/node-config-modal"

// ─── Node state derived from events ──────────────────────────────────────────

interface NodeState {
  node_id: string
  node_type: string
  label: string
  status: "running" | "success" | "error" | "skipped" | "handled_error"
  duration_ms?: number
  output?: Record<string, unknown>
  error?: string
}

function buildNodeStates(events: WorkflowTestEvent[]): NodeState[] {
  const order: string[] = []
  const states: Record<string, NodeState> = {}

  for (const event of events) {
    if (event.type === "node_start") {
      if (!states[event.node_id]) order.push(event.node_id)
      states[event.node_id] = {
        node_id: event.node_id,
        node_type: event.node_type,
        label: event.label,
        status: "running",
        output: undefined,
        error: undefined,
        duration_ms: undefined,
      }
    } else if (event.type === "node_complete") {
      if (states[event.node_id]) {
        const isSkipped = event.output?.status === "skipped"
        const isHandledError = event.output?.status === "handled_error"
        states[event.node_id].status = isSkipped
          ? "skipped"
          : isHandledError
          ? "handled_error"
          : "success"
        states[event.node_id].duration_ms = event.duration_ms
        states[event.node_id].output = event.output
        states[event.node_id].error =
          isHandledError && typeof event.output?.error === "string"
            ? event.output.error
            : undefined
      }
    } else if (event.type === "node_error") {
      if (states[event.node_id]) {
        states[event.node_id].status = "error"
        states[event.node_id].duration_ms = event.duration_ms
        states[event.node_id].error = event.error
      }
    }
  }

  return order.map((id) => states[id]).filter(Boolean)
}

// ─── Main panel ───────────────────────────────────────────────────────────────

interface ExecutionPanelProps {
  events: WorkflowTestEvent[]
  isRunning: boolean
  onAbort: () => void
  onClose: () => void
  /** Quando true, o painel ganha padding-left igual a largura da sidebar
      da Biblioteca de Nos pra nao ser sobreposto por ela. */
  libraryOpen?: boolean
}

const MIN_HEIGHT = 120
const MAX_HEIGHT = 700
const LIBRARY_WIDTH = 380

export function ExecutionPanel({ events, isRunning, onAbort, onClose, libraryOpen }: ExecutionPanelProps) {
  const nodeStates = buildNodeStates(events)

  // ── Resize drag ──────────────────────────────────────────────────────────
  const [height, setHeight] = useState(320)
  const dragStartY = useRef<number | null>(null)
  const dragStartH = useRef<number>(320)

  const onResizeMouseDown = (e: React.MouseEvent) => {
    e.preventDefault()
    dragStartY.current = e.clientY
    dragStartH.current = height

    const onMove = (ev: MouseEvent) => {
      if (dragStartY.current === null) return
      const delta = dragStartY.current - ev.clientY          // drag up → taller
      const next = Math.min(MAX_HEIGHT, Math.max(MIN_HEIGHT, dragStartH.current + delta))
      setHeight(next)
    }
    const onUp = () => {
      dragStartY.current = null
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
  }

  // Selection: auto-follows last active node unless user manually picked one
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [userPicked, setUserPicked] = useState(false)

  // Auto-select last active/completed node
  useEffect(() => {
    if (userPicked) return
    const last = nodeStates[nodeStates.length - 1]
    if (last) setSelectedId(last.node_id)
  })

  const handleSelect = (id: string) => {
    setSelectedId(id)
    setUserPicked(true)
  }

  // When execution restarts, reset user pick so auto-follow resumes
  useEffect(() => {
    const hasStart = events.some((e) => e.type === "execution_start")
    if (hasStart) setUserPicked(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events.length === 1 && events[0]?.type === "execution_start"])

  const selectedNode = nodeStates.find((n) => n.node_id === selectedId) ?? null

  const completeEvent = [...events]
    .reverse()
    .find((e) => e.type === "execution_complete") as
    | Extract<WorkflowTestEvent, { type: "execution_complete" }>
    | undefined

  return (
    <div
      className="flex shrink-0 flex-col border-t border-border bg-card transition-[padding] duration-300 ease-out"
      style={{
        height,
        paddingLeft: libraryOpen ? LIBRARY_WIDTH : 0,
      }}
    >
      {/* ── Resize handle ── */}
      <div
        onMouseDown={onResizeMouseDown}
        className="group flex h-1.5 w-full shrink-0 cursor-ns-resize items-center justify-center"
        aria-label="Redimensionar painel"
      >
        <div className="h-0.5 w-10 rounded-full bg-border transition-colors group-hover:bg-muted-foreground/40" />
      </div>

      {/* ── Header ── */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3">
        <div className="flex items-center gap-2">
          {isRunning ? (
            <>
              <Loader2 className="size-3.5 animate-spin text-amber-500" />
              <span className="text-xs font-semibold">Executando…</span>
            </>
          ) : completeEvent ? (
            <>
              {completeEvent.status === "SUCCESS" ? (
                <CheckCircle2 className="size-3.5 text-emerald-500" />
              ) : (
                <XCircle className="size-3.5 text-red-500" />
              )}
              <span
                className={cn(
                  "text-xs font-semibold",
                  completeEvent.status === "SUCCESS" ? "text-emerald-600" : "text-red-600",
                )}
              >
                {completeEvent.status === "SUCCESS" ? "Concluído" : "Falhou"} em{" "}
                {(completeEvent.duration_ms / 1000).toFixed(2)}s
              </span>
            </>
          ) : (
            <span className="text-xs font-semibold text-muted-foreground">Logs de execução</span>
          )}
        </div>

        <div className="flex items-center gap-1">
          {isRunning && (
            <button
              type="button"
              onClick={onAbort}
              className="flex items-center gap-1 rounded px-2 py-0.5 text-[11px] font-medium text-destructive transition-colors hover:bg-muted"
            >
              <Square className="size-3" />
              Parar
            </button>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
            aria-label="Fechar painel"
          >
            <X className="size-3.5" />
          </button>
        </div>
      </div>

      {/* ── Body: node list + detail ── */}
      <div className="flex min-h-0 flex-1 divide-x divide-border">
        {/* Left: node list */}
        <div className="w-52 shrink-0 overflow-y-auto">
          {nodeStates.length === 0 ? (
            <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
              Aguardando…
            </div>
          ) : (
            <ul className="py-1">
              {nodeStates.map((node) => (
                <NodeListItem
                  key={node.node_id}
                  node={node}
                  isSelected={selectedId === node.node_id}
                  onClick={() => handleSelect(node.node_id)}
                />
              ))}
            </ul>
          )}
        </div>

        {/* Right: detail panel */}
        <div className="flex min-w-0 flex-1 flex-col">
          {selectedNode ? (
            <NodeDetail node={selectedNode} />
          ) : (
            <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
              Selecione um nó para ver os dados
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Node list item ───────────────────────────────────────────────────────────

function NodeListItem({
  node,
  isSelected,
  onClick,
}: {
  node: NodeState
  isSelected: boolean
  onClick: () => void
}) {
  const definition = getNodeDefinition(node.node_type)
  const Icon = getNodeIcon(definition?.icon ?? "Zap")

  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={cn(
          "flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors",
          isSelected
            ? "bg-accent text-foreground"
            : "text-muted-foreground hover:bg-muted/50 hover:text-foreground",
        )}
      >
        {/* Status icon */}
        <div className="shrink-0">
          {node.status === "running" && (
            <Loader2 className="size-3.5 animate-spin text-amber-500" />
          )}
          {node.status === "success" && (
            <CheckCircle2 className="size-3.5 text-emerald-500" />
          )}
          {node.status === "handled_error" && (
            <AlertTriangle className="size-3.5 text-rose-500" />
          )}
          {node.status === "error" && (
            <XCircle className="size-3.5 text-red-500" />
          )}
          {node.status === "skipped" && (
            <div className="size-3.5 rounded-full border border-muted-foreground/40" />
          )}
        </div>

        {/* Node icon + label */}
        <Icon className="size-3.5 shrink-0 opacity-60" />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[12px] font-medium leading-tight">{node.label}</p>
          {node.duration_ms !== undefined && (
            <p className="text-[10px] opacity-60 tabular-nums">{node.duration_ms}ms</p>
          )}
        </div>
      </button>
    </li>
  )
}

// ─── Node detail panel ────────────────────────────────────────────────────────

function NodeDetail({ node }: { node: NodeState }) {
  if (node.status === "running") {
    return (
      <div className="flex flex-1 items-center justify-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" />
        Executando…
      </div>
    )
  }

  if (node.status === "error") {
    return (
      <div className="flex flex-col gap-2 p-4">
        <p className="text-[10px] font-bold uppercase tracking-widest text-destructive">Erro</p>
        <div className="rounded-md border border-red-500/20 bg-red-500/5 p-3 text-xs text-red-600 break-all dark:text-red-400">
          {node.error}
        </div>
      </div>
    )
  }

  if (node.status === "handled_error") {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <div className="flex items-center gap-2 border-b border-rose-500/20 bg-rose-500/5 px-4 py-3">
          <AlertTriangle className="size-4 shrink-0 text-rose-500" />
          <div>
            <p className="text-xs font-semibold text-rose-700 dark:text-rose-400">
              Erro tratado via on_error
            </p>
            <p className="text-[10px] text-muted-foreground break-all">
              {node.error ?? "Falha roteada para o ramo alternativo."}
            </p>
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-auto">
          <DataViewer
            output={node.output ?? {}}
            sourceLabel={node.label}
            sourceNodeType={node.node_type}
          />
        </div>
      </div>
    )
  }

  if (!node.output) return null

  const output = node.output

  // ── Load Node (escrita SQL) ──────────────────────────────────────────────
  const isLoad = typeof output.rows_written === "number"
  if (isLoad) {
    const disposition: Record<string, string> = {
      append: "Append",
      replace: "Replace",
      merge: "Merge",
    }
    return (
      <div className="flex flex-col gap-3 p-4">
        <div className="flex items-center gap-2 rounded-lg border border-emerald-500/20 bg-emerald-500/5 px-3 py-2.5">
          <DatabaseZap className="size-4 shrink-0 text-emerald-500" />
          <div>
            <p className="text-xs font-semibold text-emerald-700 dark:text-emerald-400">
              {output.rows_written as number} linha{(output.rows_written as number) !== 1 ? "s" : ""} gravadas
            </p>
            <p className="text-[10px] text-muted-foreground">
              {output.target_table as string} · {disposition[output.write_disposition as string] ?? output.write_disposition}
            </p>
          </div>
        </div>
      </div>
    )
  }

  return (
    <DataViewer
      output={output}
      sourceLabel={node.label}
      sourceNodeType={node.node_type}
    />
  )
}
