"use client"

import { useEffect, useMemo, useState } from "react"
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
import { UpstreamFieldsContext } from "@/lib/workflow/upstream-fields-context"

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

// ─── Main Modal ───────────────────────────────────────────────────────────────

export function NodeConfigModal({
  node,
  upstreamOutputs,
  currentOutput,
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
        className="flex h-[92vh] w-[96vw] max-w-[1440px] flex-col overflow-hidden rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-border px-4">
          <div className="flex items-center gap-3">
            <div
              className={cn(
                "flex size-8 items-center justify-center rounded-lg",
                iconBgMap[color],
              )}
            >
              <Icon className={cn("size-4", iconColorMap[color])} />
            </div>
            <div>
              <span className="text-sm font-semibold text-foreground">
                {label ?? definition?.label ?? node.type}
              </span>
              {definition?.description && (
                <span className="ml-2 text-xs text-muted-foreground">
                  {definition.description}
                </span>
              )}
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onExecute}
              className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground transition-colors hover:bg-primary/90"
            >
              <Play className="size-3" />
              Executar
            </button>
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

        {/* ── Body: 3 columns (35% / 30% / 35%) ── */}
        <div className="flex min-h-0 flex-1 divide-x divide-border">
          {/* LEFT: Input data */}
          <div className="flex min-h-0 min-w-[300px] flex-[7] flex-col">
            <InputPanel upstreamOutputs={upstreamOutputs} />
          </div>

          {/* CENTER: Parameters */}
          <div className="flex min-h-0 min-w-[260px] flex-[6] flex-col">
            <PanelHeader label="Parâmetros" />
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
              <UpstreamFieldsContext.Provider value={upstreamColumns}>
                <NodeConfigFields node={node} onUpdate={onUpdate} />
              </UpstreamFieldsContext.Provider>
            </div>
          </div>

          {/* RIGHT: Output data */}
          <div className="flex min-h-0 min-w-[300px] flex-[7] flex-col">
            <OutputPanel currentOutput={currentOutput} onExecute={onExecute} />
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
}: {
  currentOutput: NodeExecState | null
  onExecute: () => void
}) {
  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <PanelHeader label="Output" />

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
            {columns.map((col) => {
              const value = sampleRow?.[col]
              const type = detectFieldType(value)

              return (
                <div
                  key={col}
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
                  className="group flex cursor-grab items-center gap-1.5 py-1.5 pl-5 pr-3 transition-colors hover:bg-muted/30 active:cursor-grabbing"
                >
                  <GripVertical className="size-3 shrink-0 text-muted-foreground/0 transition-colors group-hover:text-muted-foreground/40" />
                  <TypeIcon type={type} />
                  <span className="shrink-0 text-[11px] font-medium text-foreground">
                    {col}
                  </span>
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
          {columns.map((col) => (
            <th
              key={col}
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
            {columns.map((col) => (
              <td
                key={col}
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
