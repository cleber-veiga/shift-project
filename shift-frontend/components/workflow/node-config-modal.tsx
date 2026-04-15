"use client"

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { type Node } from "@xyflow/react"
import {
  ArrowRightLeft,
  Braces,
  ChevronDown,
  ChevronRight,
  GripVertical,
  Hash,
  List,
  Loader2,
  Pin,
  PinOff,
  Play,
  Table2,
  ToggleLeft,
  Type,
  X,
  XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { getNodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import { NodeConfigFields } from "@/components/workflow/node-config-panel"
import type { NodeExecState } from "@/lib/workflow/execution-context"
import { UpstreamFieldsContext, UsedSourcesContext } from "@/lib/workflow/upstream-fields-context"

// ─── Types ────────────────────────────────────────────────────────────────────

export interface UpstreamOutput {
  nodeId: string
  label: string
  nodeType: string
  output: Record<string, unknown> | null
}

interface NodeConfigModalProps {
  node: Node
  upstreamOutputs: UpstreamOutput[]
  currentOutput: NodeExecState | null
  isExecuting?: boolean
  onClose: () => void
  onUpdate: (nodeId: string, data: Record<string, unknown>) => void
  onExecute: () => void
}

// ─── Color maps ───────────────────────────────────────────────────────────────

const iconBgMap: Record<string, string> = {
  amber:   "bg-amber-100 dark:bg-amber-500/20",
  blue:    "bg-blue-100 dark:bg-blue-500/20",
  violet:  "bg-violet-100 dark:bg-violet-500/20",
  emerald: "bg-emerald-100 dark:bg-emerald-500/20",
  pink:    "bg-pink-100 dark:bg-pink-500/20",
}

const iconColorMap: Record<string, string> = {
  amber:   "text-amber-600 dark:text-amber-400",
  blue:    "text-blue-600 dark:text-blue-400",
  violet:  "text-violet-600 dark:text-violet-400",
  emerald: "text-emerald-600 dark:text-emerald-400",
  pink:    "text-pink-600 dark:text-pink-400",
}

// ─── Type detection helpers ──────────────────────────────────────────────────

type FieldType = "string" | "number" | "boolean" | "array" | "object" | "null"

function detectFieldType(value: unknown): FieldType {
  if (value === null || value === undefined) return "null"
  if (typeof value === "string") return "string"
  if (typeof value === "number") return "number"
  if (typeof value === "boolean") return "boolean"
  if (Array.isArray(value)) return "array"
  if (typeof value === "object") return "object"
  return "string"
}

function TypeIcon({ type, className }: { type: FieldType; className?: string }) {
  const base = cn("size-3 shrink-0", className)
  switch (type) {
    case "string":
      return <Type className={cn(base, "text-emerald-500")} />
    case "number":
      return <Hash className={cn(base, "text-blue-500")} />
    case "boolean":
      return <ToggleLeft className={cn(base, "text-amber-500")} />
    case "array":
      return <List className={cn(base, "text-violet-500")} />
    case "object":
      return <Braces className={cn(base, "text-pink-500")} />
    case "null":
      return <span className={cn("text-[9px] font-mono italic text-muted-foreground/50", className)}>∅</span>
    default:
      return <Type className={cn(base, "text-muted-foreground")} />
  }
}

function typeLabel(type: FieldType): string {
  switch (type) {
    case "string": return "String"
    case "number": return "Number"
    case "boolean": return "Boolean"
    case "array": return "Array"
    case "object": return "Object"
    case "null": return "Null"
    default: return "Unknown"
  }
}

// ─── Persisted panel widths (survives modal close/reopen within session) ─────

const _savedPanelWidths: { left: number | null; center: number | null } = {
  left: null,
  center: null,
}

// ─── Main Modal ───────────────────────────────────────────────────────────────

export function NodeConfigModal({
  node,
  upstreamOutputs,
  currentOutput,
  isExecuting: isExecutingProp,
  onClose,
  onUpdate,
  onExecute,
}: NodeConfigModalProps) {
  const definition = getNodeDefinition(node.type ?? "")
  const color = definition?.color ?? "blue"
  const Icon = getNodeIcon(definition?.icon ?? "Database")
  const label = (node.data as Record<string, unknown>).label as string | undefined

  // Compute upstream columns for the UpstreamFieldsContext
  const upstreamColumns = useMemo(() => {
    for (const up of upstreamOutputs) {
      if (up.output && Array.isArray(up.output.columns)) {
        return up.output.columns as string[]
      }
    }
    return []
  }, [upstreamOutputs])

  // Compute which source fields are already mapped (used by this node's mappings)
  const usedSources = useMemo(() => {
    const data = node.data as Record<string, unknown>
    const mappings = Array.isArray(data?.mappings)
      ? (data.mappings as Array<{ source?: string; valueType?: string; exprTemplate?: string }>)
      : []
    const sources = new Set<string>()
    for (const m of mappings) {
      if (m.valueType === "field" && m.source) {
        sources.add(m.source)
      } else if (m.valueType === "expression" && m.exprTemplate) {
        const re = /\{\{([^}]+)\}\}/g
        let match: RegExpExecArray | null
        while ((match = re.exec(m.exprTemplate)) !== null) {
          sources.add(match[1])
        }
      }
    }
    return sources
  }, [node.data])

  const isRunning = isExecutingProp || currentOutput?.status === "running"

  // ── Resizable panels ──────────────────────────────────────────────────────
  const containerRef = useRef<HTMLDivElement>(null)
  const [leftWidth, setLeftWidth]     = useState<number | null>(_savedPanelWidths.left)
  const [centerWidth, setCenterWidth] = useState<number | null>(_savedPanelWidths.center)

  // Persist widths so they survive modal close/reopen
  useEffect(() => { _savedPanelWidths.left = leftWidth }, [leftWidth])
  useEffect(() => { _savedPanelWidths.center = centerWidth }, [centerWidth])
  const draggingRef = useRef<"left" | "right" | null>(null)
  const startXRef   = useRef(0)
  const startLRef   = useRef(0)
  const startCRef   = useRef(0)

  const leftRef   = useRef<HTMLDivElement>(null)
  const centerRef = useRef<HTMLDivElement>(null)

  const handlePointerDown = useCallback(
    (side: "left" | "right", e: React.PointerEvent) => {
      e.preventDefault()
      draggingRef.current = side
      startXRef.current = e.clientX
      startLRef.current = leftRef.current?.offsetWidth ?? 0
      startCRef.current = centerRef.current?.offsetWidth ?? 0
      document.body.style.cursor = "col-resize"
      document.body.style.userSelect = "none"
    },
    [],
  )

  useEffect(() => {
    function onMove(e: PointerEvent) {
      if (!draggingRef.current || !containerRef.current) return
      const dx = e.clientX - startXRef.current
      const totalW = containerRef.current.offsetWidth
      const MIN = 240
      if (draggingRef.current === "left") {
        const newLeft = Math.max(MIN, Math.min(startLRef.current + dx, totalW - MIN * 2 - 16))
        setLeftWidth(newLeft)
      } else {
        const newCenter = Math.max(MIN, Math.min(startCRef.current + dx, totalW - MIN * 2 - 16))
        setCenterWidth(newCenter)
      }
    }
    function onUp() {
      if (!draggingRef.current) return
      draggingRef.current = null
      document.body.style.cursor = ""
      document.body.style.userSelect = ""
    }
    document.addEventListener("pointermove", onMove)
    document.addEventListener("pointerup", onUp)
    return () => {
      document.removeEventListener("pointermove", onMove)
      document.removeEventListener("pointerup", onUp)
    }
  }, [])

  // Close on Escape
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    document.addEventListener("keydown", onKey)
    return () => document.removeEventListener("keydown", onKey)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 backdrop-blur-[2px]"
      onClick={onClose}
    >
      <div
        className="flex h-[96vh] w-[98vw] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header: icon + editable name + description + close ── */}
        <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
          <div
            className={cn(
              "flex size-8 shrink-0 items-center justify-center rounded-lg",
              iconBgMap[color],
            )}
          >
            <Icon className={cn("size-4", iconColorMap[color])} />
          </div>
          <input
            type="text"
            value={label ?? definition?.label ?? node.type ?? ""}
            onChange={(e) =>
              onUpdate(node.id, {
                ...(node.data as Record<string, unknown>),
                label: e.target.value,
              })
            }
            placeholder="Nome do nó..."
            className="h-8 min-w-0 max-w-[300px] rounded-md border border-transparent bg-transparent px-2 text-sm font-semibold text-foreground outline-none transition-colors placeholder:text-muted-foreground hover:border-input focus:border-input focus:ring-1 focus:ring-primary"
          />
          <div className="ml-auto">
            <button
              type="button"
              onClick={onClose}
              className="flex size-8 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              aria-label="Fechar"
            >
              <X className="size-4" />
            </button>
          </div>
        </div>

        {/* ── Body: 3 resizable columns ── */}
        <div ref={containerRef} className="flex min-h-0 flex-1">
          {/* LEFT: Input data */}
          <div
            ref={leftRef}
            className="flex min-h-0 min-w-[240px] flex-col"
            style={leftWidth ? { width: leftWidth, flexShrink: 0, flexGrow: 0 } : { flex: 7 }}
          >
            <UsedSourcesContext.Provider value={usedSources}>
              <InputPanel upstreamOutputs={upstreamOutputs} />
            </UsedSourcesContext.Provider>
          </div>

          {/* Resize handle LEFT ↔ CENTER */}
          <div
            className="group relative z-10 flex w-2 shrink-0 cursor-col-resize items-center justify-center border-x border-border bg-transparent transition-colors hover:bg-primary/5"
            onPointerDown={(e) => handlePointerDown("left", e)}
          >
            <div className="h-8 w-[3px] rounded-full bg-border transition-colors group-hover:bg-primary/40 group-active:bg-primary/60" />
          </div>

          {/* CENTER: Parameters */}
          <div
            ref={centerRef}
            className="flex min-h-0 min-w-[240px] flex-col"
            style={centerWidth ? { width: centerWidth, flexShrink: 0, flexGrow: 0 } : { flex: 6 }}
          >
            {/* Parameters header with execute button */}
            <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Parâmetros
              </span>
              <button
                type="button"
                onClick={onExecute}
                disabled={isRunning}
                className={cn(
                  "flex items-center gap-1.5 rounded-lg px-3 py-1 text-[11px] font-semibold transition-colors",
                  isRunning
                    ? "bg-primary/70 text-primary-foreground cursor-not-allowed"
                    : "bg-primary text-primary-foreground hover:bg-primary/90",
                )}
              >
                {isRunning
                  ? <><Loader2 className="size-3 animate-spin" /> Executando…</>
                  : <><Play className="size-3" /> Executar</>
                }
              </button>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
              <UpstreamFieldsContext.Provider value={upstreamColumns}>
                <NodeConfigFields node={node} onUpdate={onUpdate} />
              </UpstreamFieldsContext.Provider>
            </div>
          </div>

          {/* Resize handle CENTER ↔ RIGHT */}
          <div
            className="group relative z-10 flex w-2 shrink-0 cursor-col-resize items-center justify-center border-x border-border bg-transparent transition-colors hover:bg-primary/5"
            onPointerDown={(e) => handlePointerDown("right", e)}
          >
            <div className="h-8 w-[3px] rounded-full bg-border transition-colors group-hover:bg-primary/40 group-active:bg-primary/60" />
          </div>

          {/* RIGHT: Output data */}
          <div className="flex min-h-0 min-w-[240px] flex-1 flex-col">
            <OutputPanel
              currentOutput={currentOutput}
              onExecute={onExecute}
              isPinned={Boolean((node.data as Record<string, unknown>)?.pinnedOutput)}
              onPin={() => {
                if (!currentOutput?.output) return
                onUpdate(node.id, {
                  ...(node.data as Record<string, unknown>),
                  pinnedOutput: currentOutput.output,
                })
              }}
              onUnpin={() => {
                const { pinnedOutput: _, ...rest } = node.data as Record<string, unknown>
                onUpdate(node.id, rest)
              }}
            />
          </div>
        </div>

        {/* ── Footer ── */}
        <div className="flex h-8 shrink-0 items-center justify-between border-t border-border px-4">
          <span className="text-[10px] text-muted-foreground">
            {node.type} · {node.id}
          </span>
          {currentOutput?.duration_ms !== undefined && (
            <span className="text-[10px] tabular-nums text-muted-foreground">
              {currentOutput.duration_ms}ms
            </span>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Input Panel (left) ──────────────────────────────────────────────────────

function InputPanel({ upstreamOutputs }: { upstreamOutputs: UpstreamOutput[] }) {
  const [selectedIdx, setSelectedIdx] = useState(0)

  // Reset selection if upstream list changes
  useEffect(() => {
    setSelectedIdx(0)
  }, [upstreamOutputs.length])

  const selected = upstreamOutputs[selectedIdx] ?? null

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <PanelHeader label="Input" />

      {/* Upstream node selector */}
      {upstreamOutputs.length > 1 && (
        <div className="shrink-0 border-b border-border px-2 py-1.5">
          <div className="flex gap-1">
            {upstreamOutputs.map((up, i) => (
              <button
                key={up.nodeId}
                type="button"
                onClick={() => setSelectedIdx(i)}
                className={cn(
                  "flex-1 truncate rounded-md px-2 py-1 text-[11px] font-medium transition-colors",
                  i === selectedIdx
                    ? "bg-accent text-foreground"
                    : "text-muted-foreground hover:text-foreground",
                )}
                title={up.label}
              >
                {up.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {upstreamOutputs.length === 0 ? (
        <EmptyState
          icon={<ArrowRightLeft className="size-5 text-muted-foreground/30" />}
          title="Sem nós conectados"
          subtitle="Conecte um nó anterior para ver os dados de entrada."
        />
      ) : !selected?.output ? (
        <EmptyState
          icon={<Play className="size-5 text-muted-foreground/30" />}
          title="Sem dados de entrada"
          subtitle="Execute os nós anteriores para ver os dados aqui."
        />
      ) : (
        <DataViewer
          output={selected.output}
          sourceLabel={selected.label}
          sourceNodeType={selected.nodeType}
        />
      )}
    </div>
  )
}

// ─── Output Panel (right) ────────────────────────────────────────────────────

function OutputPanel({
  currentOutput,
  onExecute,
  isPinned,
  onPin,
  onUnpin,
}: {
  currentOutput: NodeExecState | null
  onExecute: () => void
  isPinned: boolean
  onPin: () => void
  onUnpin: () => void
}) {
  const canPin = Boolean(currentOutput?.output) && !currentOutput?.is_pinned

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      {/* Header with pin button */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Output
        </span>
        {(isPinned || canPin) && (
          <button
            type="button"
            onClick={isPinned ? onUnpin : onPin}
            title={isPinned ? "Liberar dados fixados" : "Fixar dados (não re-executa ao recarregar)"}
            className={cn(
              "flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium transition-colors",
              isPinned
                ? "bg-amber-500/10 text-amber-600 hover:bg-amber-500/20 dark:text-amber-400"
                : "text-muted-foreground/60 hover:bg-muted hover:text-foreground",
            )}
          >
            {isPinned
              ? <><PinOff className="size-3" /> Liberar</>
              : <><Pin className="size-3" /> Fixar</>
            }
          </button>
        )}
      </div>

      {/* Pinned banner */}
      {isPinned && (
        <div className="flex items-center gap-2 border-b border-amber-500/20 bg-amber-500/5 px-3 py-2">
          <Pin className="size-3 shrink-0 text-amber-500" />
          <span className="text-[10px] text-amber-600 dark:text-amber-400">
            Dados fixados — nó não será re-executado
          </span>
        </div>
      )}

      {currentOutput?.status === "running" ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-xs text-muted-foreground">
          <Loader2 className="size-3.5 animate-spin" />
          Executando…
        </div>
      ) : currentOutput?.status === "error" ? (
        <div className="flex flex-col gap-2 p-3">
          <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-destructive">
            <XCircle className="size-3" />
            Erro
          </div>
          <div className="rounded-md border border-red-500/20 bg-red-500/5 p-2.5 text-[11px] text-red-600 break-all dark:text-red-400">
            {currentOutput.error}
          </div>
        </div>
      ) : currentOutput?.output ? (
        <DataViewer output={currentOutput.output} />
      ) : (
        <EmptyState
          icon={<Play className="size-5 text-muted-foreground/30" />}
          title="Sem dados de saída"
          subtitle=""
        >
          <button
            type="button"
            onClick={onExecute}
            className="mt-2 rounded-md border border-border px-3 py-1.5 text-[11px] font-medium text-foreground transition-colors hover:bg-muted"
          >
            Executar
          </button>
        </EmptyState>
      )}
    </div>
  )
}

// ─── Shared Data Viewer (schema / table / json) ─────────────────────────────

type ViewTab = "schema" | "table" | "json"

function DataViewer({
  output,
  sourceLabel,
  sourceNodeType,
}: {
  output: Record<string, unknown>
  sourceLabel?: string
  sourceNodeType?: string
}) {
  const [tab, setTab] = useState<ViewTab>("schema")

  const columns = Array.isArray(output.columns)
    ? (output.columns as string[])
    : undefined
  const rows = Array.isArray(output.rows)
    ? (output.rows as Array<Record<string, unknown>>)
    : undefined
  const hasTable = columns !== undefined && rows !== undefined

  // For schema view, get the first row as sample
  const sampleRow = rows?.[0] ?? null

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Tabs */}
      <div className="flex h-8 shrink-0 items-center gap-1 border-b border-border px-2.5">
        <TabBtn
          active={tab === "schema"}
          onClick={() => setTab("schema")}
          icon={<List className="size-3" />}
          label="Schema"
        />
        {hasTable && (
          <TabBtn
            active={tab === "table"}
            onClick={() => setTab("table")}
            icon={<Table2 className="size-3" />}
            label="Tabela"
          />
        )}
        <TabBtn
          active={tab === "json"}
          onClick={() => setTab("json")}
          icon={<Braces className="size-3" />}
          label="JSON"
        />
        {hasTable && rows && (
          <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
            {rows.length} {rows.length === 1 ? "item" : "itens"}
          </span>
        )}
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-auto">
        {tab === "schema" ? (
          <SchemaView
            columns={columns}
            sampleRow={sampleRow}
            output={output}
            sourceLabel={sourceLabel}
            sourceNodeType={sourceNodeType}
          />
        ) : hasTable && tab === "table" ? (
          <MiniTable columns={columns!} rows={rows!} />
        ) : (
          <pre className="p-2.5 font-mono text-[10px] leading-relaxed text-foreground whitespace-pre-wrap break-all">
            {JSON.stringify(output, null, 2)}
          </pre>
        )}
      </div>
    </div>
  )
}

// ─── Schema View (N8N-style) ────────────────────────────────────────────────

function SchemaView({
  columns,
  sampleRow,
  output,
  sourceLabel,
  sourceNodeType,
}: {
  columns?: string[]
  sampleRow: Record<string, unknown> | null
  output: Record<string, unknown>
  sourceLabel?: string
  sourceNodeType?: string
}) {
  const [expanded, setExpanded] = useState(true)
  const usedSources = useContext(UsedSourcesContext)
  const rows = Array.isArray(output.rows) ? output.rows as Array<Record<string, unknown>> : []

  // If we have columns, show structured schema tree
  if (columns && columns.length > 0) {
    const nodeLabel = sourceLabel || "Dados"
    const NodeIcon = sourceNodeType
      ? getNodeIcon(getNodeDefinition(sourceNodeType)?.icon ?? "Database")
      : null

    return (
      <div className="py-2">
        {/* Root node: collapsible */}
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="flex w-full items-center gap-2 px-3 py-1.5 text-left transition-colors hover:bg-muted/50"
        >
          {expanded ? (
            <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight className="size-3 shrink-0 text-muted-foreground" />
          )}
          {NodeIcon && (
            <NodeIcon className="size-3.5 shrink-0 text-muted-foreground" />
          )}
          <span className="text-xs font-medium text-foreground truncate">
            {nodeLabel}
          </span>
          <span className="ml-auto shrink-0 text-[10px] tabular-nums text-muted-foreground">
            {rows.length} {rows.length === 1 ? "item" : "itens"}
          </span>
        </button>

        {/* Fields */}
        {expanded && (
          <div className="mt-0.5">
            {columns.map((col, ci) => {
              const value   = sampleRow?.[col]
              const type    = detectFieldType(value)
              const isUsed  = usedSources.has(col)

              return (
                <div
                  key={`${col}-${ci}`}
                  draggable
                  onDragStart={(e) => {
                    e.dataTransfer.setData("application/x-shift-field", col)
                    e.dataTransfer.effectAllowed = "copyMove"
                    // Custom drag image
                    const ghost = document.createElement("div")
                    ghost.textContent = col
                    ghost.style.cssText =
                      "position:fixed;top:-100px;left:-100px;padding:4px 12px;border-radius:6px;font-size:11px;font-weight:600;background:#3b82f6;color:#fff;white-space:nowrap;pointer-events:none;z-index:9999"
                    document.body.appendChild(ghost)
                    e.dataTransfer.setDragImage(ghost, 0, 0)
                    requestAnimationFrame(() => ghost.remove())
                  }}
                  className={cn(
                    "group flex cursor-grab items-center gap-1.5 py-1.5 pl-5 pr-3 transition-colors active:cursor-grabbing",
                    isUsed
                      ? "bg-primary/[0.05] hover:bg-primary/[0.09]"
                      : "hover:bg-muted/30",
                  )}
                >
                  <GripVertical className="size-3 shrink-0 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/40" />
                  <TypeIcon type={type} />
                  <span className={cn(
                    "shrink-0 text-[11px] font-medium",
                    isUsed ? "text-primary" : "text-foreground",
                  )}>
                    {col}
                  </span>
                  {isUsed && (
                    <span
                      title="Campo já mapeado"
                      className="ml-1 size-1.5 shrink-0 rounded-full bg-primary/60"
                    />
                  )}
                  <span className="ml-auto max-w-[50%] truncate text-right text-[11px] text-muted-foreground" title={value != null ? String(value) : "null"}>
                    {value == null ? (
                      <span className="italic text-muted-foreground/40">null</span>
                    ) : typeof value === "object" ? (
                      <span className="font-mono text-[10px]">
                        {Array.isArray(value) ? `[${value.length}]` : "{...}"}
                      </span>
                    ) : (
                      String(value)
                    )}
                  </span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    )
  }

  // Fallback: show raw output as a schema-like key/value tree
  const entries = Object.entries(output)
  if (entries.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-[11px] text-muted-foreground">
        Sem dados.
      </div>
    )
  }

  return (
    <div className="py-2">
      {entries.map(([key, value]) => {
        const type = detectFieldType(value)
        return (
          <div
            key={key}
            className="flex items-center gap-2 py-1.5 pl-4 pr-3 transition-colors hover:bg-muted/30"
          >
            <TypeIcon type={type} />
            <span className="shrink-0 text-[11px] font-medium text-foreground">
              {key}
            </span>
            <span className="ml-auto max-w-[60%] truncate text-right text-[11px] text-muted-foreground">
              {value == null ? (
                <span className="italic text-muted-foreground/40">null</span>
              ) : typeof value === "object" ? (
                <span className="font-mono text-[10px]">
                  {Array.isArray(value)
                    ? `Array[${(value as unknown[]).length}]`
                    : `{${Object.keys(value as object).length} campos}`}
                </span>
              ) : (
                String(value)
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ─── Mini Table ──────────────────────────────────────────────────────────────

function MiniTable({
  columns,
  rows,
}: {
  columns: string[]
  rows: Array<Record<string, unknown>>
}) {
  if (rows.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-[11px] text-muted-foreground">
        Nenhuma linha.
      </div>
    )
  }

  return (
    <table className="w-full min-w-max border-separate border-spacing-0 text-[10px]">
      <thead className="sticky top-0 z-10">
        <tr className="bg-muted/80 backdrop-blur-sm">
          <th className="sticky left-0 z-20 w-8 border-b border-r border-border bg-muted/80 px-1.5 py-1.5 text-center font-semibold text-muted-foreground backdrop-blur-sm">
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
            <td className="sticky left-0 z-10 border-b border-r border-border/40 bg-card px-1.5 py-1 text-center tabular-nums text-muted-foreground/50">
              {i + 1}
            </td>
            {columns.map((col, ci) => (
              <td
                key={`${col}-${ci}`}
                className="max-w-[260px] truncate whitespace-nowrap border-b border-r border-border/40 px-3 py-1 text-foreground last:border-r-0"
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

// ─── Shared UI ───────────────────────────────────────────────────────────────

function PanelHeader({ label }: { label: string }) {
  return (
    <div className="flex h-9 shrink-0 items-center border-b border-border px-3">
      <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
        {label}
      </span>
    </div>
  )
}

function TabBtn({
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

function EmptyState({
  icon,
  title,
  subtitle,
  children,
}: {
  icon: React.ReactNode
  title: string
  subtitle: string
  children?: React.ReactNode
}) {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-1.5 px-4 text-center">
      {icon}
      <p className="text-xs font-medium text-muted-foreground">{title}</p>
      {subtitle && (
        <p className="text-[10px] leading-relaxed text-muted-foreground/70">{subtitle}</p>
      )}
      {children}
    </div>
  )
}
