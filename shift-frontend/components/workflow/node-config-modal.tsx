"use client"

import { useCallback, useContext, useEffect, useMemo, useRef, useState } from "react"
import { type Node } from "@xyflow/react"
import {
  AlertTriangle,
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
import type { WebhookCapture } from "@/lib/api/webhooks"
import type { WorkflowIOSchema } from "@/lib/api/workflow-versions"
import { UpstreamFieldsContext, UpstreamOutputsContext, UsedSourcesContext, type UpstreamSummary } from "@/lib/workflow/upstream-fields-context"
import { fetchDuckdbPreview, type DuckDbPreviewResponse } from "@/lib/auth"

// ─── Types ────────────────────────────────────────────────────────────────────

export interface UpstreamOutput {
  nodeId: string
  label: string
  nodeType: string
  output: Record<string, unknown> | null
  depth?: number
}

interface NodeConfigModalProps {
  node: Node
  workflowId: string
  upstreamOutputs: UpstreamOutput[]
  currentOutput: NodeExecState | null
  isExecuting?: boolean
  onClose: () => void
  onUpdate: (nodeId: string, data: Record<string, unknown>) => void
  onExecute: () => void
  onWebhookTestEvent?: (capture: WebhookCapture) => void
  ioSchema?: WorkflowIOSchema
}

// ─── Color maps ───────────────────────────────────────────────────────────────

const iconBgMap: Record<string, string> = {
  amber:   "bg-amber-100 dark:bg-amber-500/20",
  blue:    "bg-blue-100 dark:bg-blue-500/20",
  violet:  "bg-violet-100 dark:bg-violet-500/20",
  emerald: "bg-emerald-100 dark:bg-emerald-500/20",
  orange:  "bg-orange-100 dark:bg-orange-500/20",
  pink:    "bg-pink-100 dark:bg-pink-500/20",
  indigo:  "bg-indigo-100 dark:bg-indigo-500/20",
  red:     "bg-red-100 dark:bg-red-500/20",
  slate:   "bg-slate-100 dark:bg-slate-500/20",
}

const iconColorMap: Record<string, string> = {
  amber:   "text-amber-600 dark:text-amber-400",
  blue:    "text-blue-600 dark:text-blue-400",
  violet:  "text-violet-600 dark:text-violet-400",
  emerald: "text-emerald-600 dark:text-emerald-400",
  orange:  "text-orange-600 dark:text-orange-400",
  pink:    "text-pink-600 dark:text-pink-400",
  indigo:  "text-indigo-600 dark:text-indigo-400",
  red:     "text-red-600 dark:text-red-400",
  slate:   "text-slate-600 dark:text-slate-400",
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
  workflowId,
  upstreamOutputs,
  currentOutput,
  isExecuting: isExecutingProp,
  onClose,
  onUpdate,
  onExecute,
  onWebhookTestEvent,
  ioSchema,
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

  // Resumo compacto dos upstreams (para pickers em node configs).
  const upstreamSummaries = useMemo<UpstreamSummary[]>(
    () =>
      upstreamOutputs.map((u) => ({
        nodeId: u.nodeId,
        label: u.label,
        nodeType: u.nodeType,
        output: u.output,
        depth: u.depth ?? 1,
      })),
    [upstreamOutputs],
  )

  // Compute which source fields are already used (mappings, conditions, switch_field)
  const usedSources = useMemo(() => {
    const data = node.data as Record<string, unknown>
    const sources = new Set<string>()

    // Mapper mappings
    const mappings = Array.isArray(data?.mappings)
      ? (data.mappings as Array<{ source?: string; valueType?: string; exprTemplate?: string }>)
      : []
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

    // IF / Filter conditions
    const conditions = Array.isArray(data?.conditions)
      ? (data.conditions as Array<{ field?: string }>)
      : []
    for (const c of conditions) {
      if (c.field) sources.add(c.field)
    }

    // Switch field
    const switchField = data?.switch_field as string | undefined
    if (switchField) sources.add(switchField)

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
                <UpstreamOutputsContext.Provider value={upstreamSummaries}>
                  <NodeConfigFields
                    node={node}
                    workflowId={workflowId}
                    onUpdate={onUpdate}
                    onWebhookTestEvent={onWebhookTestEvent}
                    ioSchema={ioSchema}
                  />
                </UpstreamOutputsContext.Provider>
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
  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <PanelHeader label="Input" />

      {upstreamOutputs.length === 0 ? (
        <EmptyState
          icon={<ArrowRightLeft className="size-5 text-muted-foreground/30" />}
          title="Sem nós conectados"
          subtitle="Conecte um nó anterior para ver os dados de entrada."
        />
      ) : (
        <div className="min-h-0 flex-1 overflow-y-auto">
          {upstreamOutputs.map((up) => (
            <UpstreamAccordion key={up.nodeId} upstream={up} />
          ))}
        </div>
      )}
    </div>
  )
}

function UpstreamAccordion({ upstream }: { upstream: UpstreamOutput }) {
  const [open, setOpen] = useState((upstream.depth ?? 1) === 1)
  const NodeIcon = getNodeIcon(getNodeDefinition(upstream.nodeType)?.icon ?? "Database")
  const hasData = upstream.output !== null

  return (
    <div className="border-b border-border last:border-b-0">
      {/* Header */}
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-muted/40"
      >
        {open
          ? <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
          : <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />}
        <NodeIcon className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate text-[12px] font-medium text-foreground">
          {upstream.label}
        </span>
        {hasData && upstream.output?.rows && Array.isArray(upstream.output.rows) && (
          <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
            {(upstream.output.rows as unknown[]).length}{" "}
            {(upstream.output.rows as unknown[]).length === 1 ? "item" : "itens"}
          </span>
        )}
        {!hasData && (
          <span className="shrink-0 text-[10px] italic text-muted-foreground/50">sem dados</span>
        )}
      </button>

      {/* Content */}
      {open && (
        hasData ? (
          <DataViewer
            output={upstream.output!}
            sourceLabel={upstream.label}
            sourceNodeType={upstream.nodeType}
            sourceNodeId={upstream.nodeId}
          />
        ) : (
          <div className="px-5 py-3 text-[11px] italic text-muted-foreground">
            Execute os nós anteriores para ver os dados aqui.
          </div>
        )
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
      ) : currentOutput?.status === "handled_error" ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="flex items-start gap-2 border-b border-rose-500/20 bg-rose-500/5 px-3 py-3">
            <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-rose-500" />
            <div className="min-w-0">
              <div className="text-[10px] font-bold uppercase tracking-widest text-rose-600 dark:text-rose-400">
                Erro tratado
              </div>
              <div className="mt-1 text-[11px] text-rose-600 break-all dark:text-rose-400">
                {currentOutput.error ?? "Falha roteada para o handle on_error."}
              </div>
            </div>
          </div>
          {currentOutput.output && <DataViewer output={currentOutput.output} />}
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

function _extractDuckDbRef(
  output: Record<string, unknown>,
): { databasePath: string; tableName: string; datasetName?: string | null } | null {
  const outputField = typeof output.output_field === "string" ? output.output_field : null
  const candidates = outputField ? [output[outputField]] : Object.values(output)
  for (const candidate of candidates) {
    if (!candidate || typeof candidate !== "object") continue
    const c = candidate as Record<string, unknown>
    // Formato sql_script: { reference: { storage_type, database_path, table_name } }
    const ref = c.reference
    if (ref && typeof ref === "object") {
      const r = ref as Record<string, unknown>
      if (r.storage_type === "duckdb" && typeof r.database_path === "string" && typeof r.table_name === "string") {
        return {
          databasePath: r.database_path,
          tableName: r.table_name,
          datasetName: typeof r.dataset_name === "string" ? r.dataset_name : null,
        }
      }
    }
    // Formato sql_database (dlt): { storage_type, database_path, table_name, dataset_name }
    if (c.storage_type === "duckdb" && typeof c.database_path === "string" && typeof c.table_name === "string") {
      return {
        databasePath: c.database_path,
        tableName: c.table_name,
        datasetName: typeof c.dataset_name === "string" ? c.dataset_name : null,
      }
    }
  }
  return null
}

// Detector genérico de dados tabulares. Cobre:
//  - Formato legado com ``columns``+``rows`` inline
//  - Referência DuckDB (sql_script/sql_database) — requer fetch remoto
//  - Array de objetos em ``output[output_field]`` ou em ``data``
//
// Usado para decidir quando exibir a aba "Tabela" e extrair dados para
// visualização inline. Retorna null quando o output não é tabular.
export type TableSource =
  | { kind: "inline"; columns: string[]; rows: Array<Record<string, unknown>> }
  | {
      kind: "duckdb"
      databasePath: string
      tableName: string
      datasetName: string | null
    }

export function extractTableSource(
  output: Record<string, unknown>,
): TableSource | null {
  if (Array.isArray(output.columns) && Array.isArray(output.rows)) {
    return {
      kind: "inline",
      columns: output.columns as string[],
      rows: output.rows as Array<Record<string, unknown>>,
    }
  }

  const duckDbRef = _extractDuckDbRef(output)
  if (duckDbRef) {
    return {
      kind: "duckdb",
      databasePath: duckDbRef.databasePath,
      tableName: duckDbRef.tableName,
      datasetName: duckDbRef.datasetName ?? null,
    }
  }

  const outputField = typeof output.output_field === "string" ? output.output_field : null
  const tried = new Set<string>()
  const fieldCandidates = [outputField, "data", "rows"].filter(
    (k): k is string => typeof k === "string" && k.length > 0,
  )
  for (const field of fieldCandidates) {
    if (tried.has(field)) continue
    tried.add(field)
    const val = output[field]
    if (
      Array.isArray(val) &&
      val.length > 0 &&
      typeof val[0] === "object" &&
      val[0] !== null &&
      !Array.isArray(val[0])
    ) {
      const rows = val as Array<Record<string, unknown>>
      const columns = Object.keys(rows[0])
      return { kind: "inline", columns, rows }
    }
  }

  return null
}

export function DataViewer({
  output,
  sourceLabel,
  sourceNodeType,
  sourceNodeId,
}: {
  output: Record<string, unknown>
  sourceLabel?: string
  sourceNodeType?: string
  sourceNodeId?: string
}) {
  const [tab, setTab] = useState<ViewTab>("schema")
  const [duckDbData, setDuckDbData] = useState<DuckDbPreviewResponse | null>(null)
  const [duckDbLoading, setDuckDbLoading] = useState(false)
  const [duckDbError, setDuckDbError] = useState<string | null>(null)

  const tableSource = useMemo(() => extractTableSource(output), [output])
  const isDuckDb = tableSource?.kind === "duckdb"
  const isInline = tableSource?.kind === "inline"

  // Reset DuckDB state when the source ref changes (new execution, different node)
  const duckDbKey = isDuckDb
    ? `${tableSource.databasePath}::${tableSource.tableName}`
    : null
  useEffect(() => {
    setDuckDbData(null)
    setDuckDbError(null)
  }, [duckDbKey])

  // Auto-fetch DuckDB preview assim que o DataViewer tem uma ref — o Schema
  // também depende dos dados (para montar a árvore de colunas N8N-style).
  useEffect(() => {
    if (!isDuckDb || duckDbData || duckDbLoading || duckDbError) return
    const src = tableSource as Extract<TableSource, { kind: "duckdb" }>
    setDuckDbLoading(true)
    fetchDuckdbPreview(src.databasePath, src.tableName, src.datasetName)
      .then((data) => setDuckDbData(data))
      .catch((err) => setDuckDbError(err?.message ?? "Erro ao carregar dados."))
      .finally(() => setDuckDbLoading(false))
  }, [isDuckDb, tableSource, duckDbData, duckDbLoading, duckDbError])

  const tableColumns = isInline
    ? (tableSource as Extract<TableSource, { kind: "inline" }>).columns
    : duckDbData?.columns ?? []
  const tableRows = isInline
    ? (tableSource as Extract<TableSource, { kind: "inline" }>).rows
    : duckDbData?.rows ?? []
  const sampleRow = tableRows[0] ?? null
  const hasTable = tableSource !== null

  const itemCount = isInline
    ? tableRows.length
    : duckDbData
      ? duckDbData.row_count
      : null
  const itemCountLabel = itemCount !== null
    ? `${itemCount}${duckDbData?.truncated ? " (prévia)" : ""} ${itemCount === 1 ? "item" : "itens"}`
    : null

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
        <span className="ml-auto text-[10px] tabular-nums text-muted-foreground">
          {duckDbLoading ? (
            <Loader2 className="size-3 animate-spin" />
          ) : (
            itemCountLabel
          )}
        </span>
      </div>

      {/* Content */}
      <div className="min-h-0 flex-1 overflow-auto">
        {tab === "schema" ? (
          <SchemaView
            columns={tableColumns.length > 0 ? tableColumns : undefined}
            sampleRow={sampleRow}
            output={output}
            sourceLabel={sourceLabel}
            sourceNodeType={sourceNodeType}
            sourceNodeId={sourceNodeId}
          />
        ) : tab === "table" ? (
          duckDbLoading ? (
            <div className="flex h-full items-center justify-center gap-2 text-xs text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Carregando prévia…
            </div>
          ) : duckDbError ? (
            <div className="flex h-full items-center justify-center p-4 text-center text-xs text-destructive">
              {duckDbError}
            </div>
          ) : (
            <MiniTable columns={tableColumns} rows={tableRows} />
          )
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
  sourceNodeId,
}: {
  columns?: string[]
  sampleRow: Record<string, unknown> | null
  output: Record<string, unknown>
  sourceLabel?: string
  sourceNodeType?: string
  sourceNodeId?: string
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
                    // Legacy payload: bare column name — consumers que
                    // operam por linha (mapper/filter/dedup/if) leem dai.
                    e.dataTransfer.setData("application/x-shift-field", col)
                    // Ref enriquecida: consumers que precisam construir
                    // um caminho completo (ex.: call_workflow → one-shot
                    // contra upstream_results) leem dai o nodeId + campo.
                    if (sourceNodeId) {
                      e.dataTransfer.setData(
                        "application/x-shift-field-ref",
                        JSON.stringify({ nodeId: sourceNodeId, field: col }),
                      )
                    }
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

  // Fallback: show raw output as a recursive schema-like key/value tree (draggable)
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
      <SchemaTreeNodes
        entries={entries}
        sourceNodeId={sourceNodeId}
        parentPath=""
        depth={0}
      />
    </div>
  )
}

function startDrag(
  e: React.DragEvent,
  field: string,
  fullPath: string,
  sourceNodeId: string | undefined,
) {
  e.stopPropagation()
  e.dataTransfer.setData("application/x-shift-field", field)
  if (sourceNodeId) {
    e.dataTransfer.setData(
      "application/x-shift-field-ref",
      JSON.stringify({ nodeId: sourceNodeId, field: fullPath }),
    )
  }
  e.dataTransfer.effectAllowed = "copyMove"
  const ghost = document.createElement("div")
  ghost.textContent = fullPath || field
  ghost.style.cssText =
    "position:fixed;top:-100px;left:-100px;padding:4px 12px;border-radius:6px;font-size:11px;font-weight:600;background:#3b82f6;color:#fff;white-space:nowrap;pointer-events:none;z-index:9999"
  document.body.appendChild(ghost)
  e.dataTransfer.setDragImage(ghost, 0, 0)
  requestAnimationFrame(() => ghost.remove())
}

function SchemaTreeNodes({
  entries,
  sourceNodeId,
  parentPath,
  depth,
}: {
  entries: [string, unknown][]
  sourceNodeId: string | undefined
  parentPath: string
  depth: number
}) {
  const usedSources = useContext(UsedSourcesContext)
  const pl = depth === 0 ? "pl-4" : depth === 1 ? "pl-8" : "pl-12"

  return (
    <>
      {entries.map(([key, value]) => {
        const fullPath = parentPath ? `${parentPath}.${key}` : key
        const isObject = value !== null && typeof value === "object" && !Array.isArray(value)
        const isArray = Array.isArray(value)
        const type = detectFieldType(value)
        const isUsed = usedSources.has(key)

        if (isObject) {
          return (
            <SchemaTreeObjectNode
              key={fullPath}
              fieldKey={key}
              fullPath={fullPath}
              value={value as Record<string, unknown>}
              sourceNodeId={sourceNodeId}
              depth={depth}
              pl={pl}
              isUsed={isUsed}
            />
          )
        }

        return (
          <div
            key={fullPath}
            draggable
            onDragStart={(e) => startDrag(e, key, fullPath, sourceNodeId)}
            className={cn(
              "group flex cursor-grab items-center gap-2 py-1.5 pr-3 transition-colors active:cursor-grabbing",
              pl,
              isUsed
                ? "bg-primary/[0.05] hover:bg-primary/[0.09]"
                : "hover:bg-muted/30",
            )}
          >
            <GripVertical className="size-3 shrink-0 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/40" />
            <TypeIcon type={type} />
            <span className={cn("shrink-0 text-[11px] font-medium", isUsed ? "text-primary" : "text-foreground")}>
              {key}
            </span>
            {isUsed && <span title="Campo já usado" className="ml-1 size-1.5 shrink-0 rounded-full bg-primary/60" />}
            <span className="ml-auto max-w-[60%] truncate text-right text-[11px] text-muted-foreground">
              {value == null ? (
                <span className="italic text-muted-foreground/40">null</span>
              ) : isArray ? (
                <span className="font-mono text-[10px]">[{(value as unknown[]).length}]</span>
              ) : (
                String(value)
              )}
            </span>
          </div>
        )
      })}
    </>
  )
}

function SchemaTreeObjectNode({
  fieldKey,
  fullPath,
  value,
  sourceNodeId,
  depth,
  pl,
  isUsed,
}: {
  fieldKey: string
  fullPath: string
  value: Record<string, unknown>
  sourceNodeId: string | undefined
  depth: number
  pl: string
  isUsed: boolean
}) {
  const [expanded, setExpanded] = useState(true)
  const childEntries = Object.entries(value)

  return (
    <div>
      <div
        draggable
        onDragStart={(e) => startDrag(e, fieldKey, fullPath, sourceNodeId)}
        className={cn(
          "group flex cursor-grab items-center gap-2 py-1.5 pr-3 transition-colors active:cursor-grabbing",
          pl,
          isUsed ? "bg-primary/[0.05] hover:bg-primary/[0.09]" : "hover:bg-muted/30",
        )}
      >
        <button
          type="button"
          onClick={(e) => { e.stopPropagation(); setExpanded(!expanded) }}
          className="flex items-center gap-1"
        >
          {expanded
            ? <ChevronDown className="size-3 shrink-0 text-muted-foreground" />
            : <ChevronRight className="size-3 shrink-0 text-muted-foreground" />}
        </button>
        <GripVertical className="size-3 shrink-0 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/40" />
        <TypeIcon type="object" />
        <span className={cn("shrink-0 text-[11px] font-medium", isUsed ? "text-primary" : "text-foreground")}>
          {fieldKey}
        </span>
        <span className="ml-auto font-mono text-[10px] text-muted-foreground">
          {`{${childEntries.length} campos}`}
        </span>
      </div>
      {expanded && childEntries.length > 0 && (
        <SchemaTreeNodes
          entries={childEntries}
          sourceNodeId={sourceNodeId}
          parentPath={fullPath}
          depth={depth + 1}
        />
      )}
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
