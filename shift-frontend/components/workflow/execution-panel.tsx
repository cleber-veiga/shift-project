"use client"

import { useEffect, useRef, useState } from "react"
import { AlertTriangle, Braces, CheckCircle2, DatabaseZap, Filter, Loader2, Square, Table2, X, XCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { getNodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import type { WorkflowTestEvent } from "@/lib/auth"

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
}

const MIN_HEIGHT = 120
const MAX_HEIGHT = 700

export function ExecutionPanel({ events, isRunning, onAbort, onClose }: ExecutionPanelProps) {
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
    <div className="flex shrink-0 flex-col border-t border-border bg-card" style={{ height }}>
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
  const [tab, setTab] = useState<"table" | "json">("table")
  const scrollRef = useRef<HTMLDivElement>(null)

  // Reset to table view when switching nodes
  useEffect(() => { setTab("table") }, [node.node_id])

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
          <pre className="p-3 font-mono text-[11px] text-foreground whitespace-pre-wrap break-all">
            {JSON.stringify(node.output ?? {}, null, 2)}
          </pre>
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

  // ── Filter: mostra resumo de filtragem ───────────────────────────────────
  const hasFilterMeta = typeof output.total_input === "number" && typeof output.filtered_out === "number"

  const rowCount = typeof output.row_count === "number" ? output.row_count : undefined
  const columns = Array.isArray(output.columns) ? (output.columns as string[]) : undefined
  const rows = Array.isArray(output.rows)
    ? (output.rows as Array<Record<string, unknown>>)
    : undefined
  const isSql = rowCount !== undefined && columns !== undefined && rows !== undefined

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Tab bar */}
      <div className="flex h-8 shrink-0 items-center gap-1 border-b border-border px-3">
        <span className="mr-2 text-[10px] font-bold uppercase tracking-widest text-muted-foreground">
          Output
        </span>
        {isSql && (
          <>
            <TabButton
              active={tab === "table"}
              onClick={() => setTab("table")}
              icon={<Table2 className="size-3" />}
              label="Tabela"
            />
            <TabButton
              active={tab === "json"}
              onClick={() => setTab("json")}
              icon={<Braces className="size-3" />}
              label="JSON"
            />
            <span className="ml-auto text-[10px] text-muted-foreground tabular-nums">
              {hasFilterMeta ? (
                <span className="flex items-center gap-1">
                  <Filter className="size-2.5" />
                  {rowCount}/{output.total_input as number} · {columns!.length} col.
                </span>
              ) : (
                <>{rowCount} linha{rowCount !== 1 ? "s" : ""} · {columns!.length} col.</>
              )}
            </span>
          </>
        )}
      </div>

      {/* Content */}
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-auto">
        {isSql && tab === "table" ? (
          <SqlTable columns={columns} rows={rows} />
        ) : (
          <pre className="p-3 font-mono text-[11px] text-foreground whitespace-pre-wrap break-all">
            {JSON.stringify(output, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

function TabButton({
  active,
  onClick,
  icon,
  label,
}: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex items-center gap-1 rounded px-2 py-0.5 text-[11px] transition-colors",
        active
          ? "bg-accent font-semibold text-foreground"
          : "text-muted-foreground hover:text-foreground",
      )}
    >
      {icon}
      {label}
    </button>
  )
}

// ─── SQL result table ─────────────────────────────────────────────────────────

function SqlTable({
  columns,
  rows,
}: {
  columns: string[]
  rows: Array<Record<string, unknown>>
}) {
  if (rows.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        Nenhuma linha retornada.
      </div>
    )
  }

  return (
    <table className="w-full min-w-max border-separate border-spacing-0 text-[11px]">
      <thead className="sticky top-0 z-10">
        <tr className="bg-muted/80 backdrop-blur-sm">
          <th className="w-8 border-b border-r border-border px-2 py-1.5 text-center font-semibold text-muted-foreground">
            #
          </th>
          {columns.map((col, ci) => (
            <th
              key={`${col}-${ci}`}
              className="whitespace-nowrap border-b border-r border-border px-3 py-1.5 text-left font-semibold text-muted-foreground last:border-r-0"
            >
              {col}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr key={i} className="hover:bg-muted/20">
            <td className="border-b border-r border-border/40 px-2 py-1.5 text-center tabular-nums text-muted-foreground/50">
              {i + 1}
            </td>
            {columns.map((col, ci) => (
              <td
                key={`${col}-${ci}`}
                className="max-w-[220px] truncate border-b border-r border-border/40 px-3 py-1.5 text-foreground last:border-r-0"
                title={row[col] != null ? String(row[col]) : undefined}
              >
                {row[col] == null ? (
                  <span className="italic text-muted-foreground/40">null</span>
                ) : (
                  String(row[col])
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  )
}
