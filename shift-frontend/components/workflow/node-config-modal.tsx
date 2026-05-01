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
  Pin,
  PinOff,
  Play,
  Table2,
  ToggleLeft,
  Type,
  X,
  XCircle,
} from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import { getNodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import { NodeConfigFields } from "@/components/workflow/node-config-panel"
import type { NodeExecState } from "@/lib/workflow/execution-context"
import type { WebhookCapture } from "@/lib/api/webhooks"
import type { WorkflowIOSchema } from "@/lib/api/workflow-versions"
import { UpstreamFieldsContext, UpstreamOutputsContext, UsedSourcesContext, type UpstreamSummary } from "@/lib/workflow/upstream-fields-context"
import { fetchDuckdbPreview, fetchNodePreview, materializePinFromBackend, type DuckDbPreviewResponse, type NodePreviewResponse } from "@/lib/auth"

// ─── Types ────────────────────────────────────────────────────────────────────

export interface UpstreamOutput {
  nodeId: string
  label: string
  nodeType: string
  output: Record<string, unknown> | null
  /** ID da execução atual — propagado para o DataViewer poder fazer
      fetch sob demanda quando o output é só uma referência DuckDB
      (caso normal hoje, já que o SSE node_complete é lean). */
  executionId?: string | null
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

// ─── Persisted panel widths (localStorage — sobrevive a F5) ──────────────────

const PANEL_WIDTHS_STORAGE_KEY = "shift.nodeConfig.panelWidths"
const PANEL_MIN_WIDTH = 240
const PANEL_HANDLE_TOTAL = 16  // 2 handles x w-2 (= 8px cada)

interface SavedPanelWidths {
  left: number | null
  center: number | null
}

function loadSavedPanelWidths(): SavedPanelWidths {
  if (typeof window === "undefined") return { left: null, center: null }
  try {
    const raw = window.localStorage.getItem(PANEL_WIDTHS_STORAGE_KEY)
    if (!raw) return { left: null, center: null }
    const parsed = JSON.parse(raw) as Partial<SavedPanelWidths>
    return {
      left: typeof parsed.left === "number" ? parsed.left : null,
      center: typeof parsed.center === "number" ? parsed.center : null,
    }
  } catch {
    return { left: null, center: null }
  }
}

function saveSavedPanelWidths(w: SavedPanelWidths) {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(PANEL_WIDTHS_STORAGE_KEY, JSON.stringify(w))
  } catch {
    // quota / privacy mode: ignora silenciosamente
  }
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

  // Compute upstream columns for the UpstreamFieldsContext.
  // Tenta multiplas estrategias em cascata pra cobrir os varios shapes que
  // ``up.output`` pode assumir (SSE lean, inline pinned, inline_data, etc.)
  // — sem isso, pickers/auto-map de nos downstream ficavam vazios pra
  // qualquer upstream que materializa em DuckDB.
  const upstreamColumns = useMemo(() => {
    function extractFromOutput(out: Record<string, unknown>): string[] | null {
      // 1) Array `columns` direto — vindo do SSE node_complete (rota nova)
      //    ou de pinned output materializado.
      if (Array.isArray(out.columns) && out.columns.length > 0) {
        return out.columns as string[]
      }
      // 2) `data` como array de dicts — caso de pinned/inline com dados crus.
      const candidates = ["data", "rows"]
      const outputField = typeof out.output_field === "string" ? out.output_field : null
      if (outputField) candidates.unshift(outputField)
      for (const key of candidates) {
        const v = out[key]
        if (
          Array.isArray(v) && v.length > 0 &&
          typeof v[0] === "object" && v[0] !== null && !Array.isArray(v[0])
        ) {
          return Object.keys(v[0] as Record<string, unknown>)
        }
      }
      // 3) `data` como dict simples (Manual com payload de objeto unico) —
      //    expoe as chaves como pseudo-colunas.
      const dataField = out.data
      if (
        dataField && typeof dataField === "object" && !Array.isArray(dataField)
        // Evita confundir DuckDbReference (storage_type/database_path) com dados.
        && !("storage_type" in (dataField as Record<string, unknown>))
        && !("database_path" in (dataField as Record<string, unknown>))
      ) {
        const keys = Object.keys(dataField as Record<string, unknown>)
        if (keys.length > 0) return keys
      }
      return null
    }

    for (const up of upstreamOutputs) {
      if (!up.output) continue
      const cols = extractFromOutput(up.output)
      if (cols && cols.length > 0) return cols
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

  // Compute which source fields are already used by the current node config.
  // Centralizado aqui pra ficar como padrão da plataforma — qualquer nó novo
  // que use uma coluna do upstream deve ter sua extração adicionada abaixo,
  // de modo que o sidebar marca automaticamente o campo como "já usado" sem
  // precisar wiring manual em cada config component.
  const usedSources = useMemo(() => {
    const data = node.data as Record<string, unknown>
    const sources = new Set<string>()
    const addIf = (v: unknown) => {
      if (typeof v === "string" && v) sources.add(v)
    }

    // ── Mapper ──────────────────────────────────────────────────────────────
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

    // ── IF / Filter ─────────────────────────────────────────────────────────
    const conditions = Array.isArray(data?.conditions)
      ? (data.conditions as Array<{ field?: string }>)
      : []
    for (const c of conditions) {
      addIf(c.field)
    }

    // ── Switch ──────────────────────────────────────────────────────────────
    addIf(data?.switch_field)

    // ── Sort ────────────────────────────────────────────────────────────────
    const sortColumns = Array.isArray(data?.sort_columns)
      ? (data.sort_columns as Array<{ column?: string }>)
      : []
    for (const sc of sortColumns) addIf(sc.column)

    // ── Aggregator ──────────────────────────────────────────────────────────
    const groupBy = Array.isArray(data?.group_by) ? (data.group_by as unknown[]) : []
    for (const g of groupBy) addIf(g)
    const aggregations = Array.isArray(data?.aggregations)
      ? (data.aggregations as Array<{ column?: string | null }>)
      : []
    for (const a of aggregations) addIf(a.column)

    // ── Pivot ──────────────────────────────────────────────────────────────
    const pivotIndex = Array.isArray(data?.index_columns) ? (data.index_columns as unknown[]) : []
    for (const c of pivotIndex) addIf(c)
    addIf(data?.pivot_column)
    addIf(data?.value_column)

    // ── Unpivot ────────────────────────────────────────────────────────────
    // index_columns ja coberto acima (mesmo nome de campo). value_columns
    // sao colunas adicionais a marcar como usadas (lista de strings).
    const unpivotValueCols = Array.isArray(data?.value_columns)
      ? (data.value_columns as unknown[])
      : []
    for (const c of unpivotValueCols) addIf(c)

    // ── Text → Rows ────────────────────────────────────────────────────────
    addIf(data?.column_to_split)

    // ── Math (extrai colunas do SQL e dos estados de UI dos modos
    //   estruturados para não depender só do parsing best-effort do SQL) ─────
    const expressions = Array.isArray(data?.expressions)
      ? (data.expressions as Array<Record<string, unknown>>)
      : []
    for (const e of expressions) {
      // SQL compilado: pega tudo entre aspas duplas (referência de coluna).
      const sql = typeof e.expression === "string" ? e.expression : ""
      const re = /"([^"]+)"/g
      let match: RegExpExecArray | null
      while ((match = re.exec(sql)) !== null) sources.add(match[1])

      // Estado UI Cálculo
      const calc = e._calc as { operands?: Array<{ kind?: string; value?: string }> } | undefined
      for (const op of calc?.operands ?? []) {
        if (op.kind === "field") addIf(op.value)
      }
      // Estado UI Condição
      const cond = e._cond as
        | {
            branches?: Array<{
              left?: { kind?: string; value?: string }
              right?: { kind?: string; value?: string }
              then?: { kind?: string; value?: string }
            }>
            fallback?: { kind?: string; value?: string }
          }
        | undefined
      for (const b of cond?.branches ?? []) {
        if (b.left?.kind === "field") addIf(b.left.value)
        if (b.right?.kind === "field") addIf(b.right.value)
        if (b.then?.kind === "field") addIf(b.then.value)
      }
      if (cond?.fallback?.kind === "field") addIf(cond.fallback.value)
      // Estado UI Texto
      const text = e._text as
        | { source?: string; transforms?: Array<{ params?: Record<string, string> }> }
        | undefined
      addIf(text?.source)
      for (const t of text?.transforms ?? []) {
        // O parâmetro ``other`` do "Juntar com outra coluna" também é uma ref
        addIf(t.params?.other)
      }
    }

    // ── Deduplication / Record ID ──────────────────────────────────────────
    const partitionBy = Array.isArray(data?.partition_by)
      ? (data.partition_by as unknown[])
      : []
    for (const p of partitionBy) addIf(p)
    const orderBy = data?.order_by
    if (typeof orderBy === "string") {
      addIf(orderBy)
    } else if (Array.isArray(orderBy)) {
      for (const ob of orderBy) {
        if (ob && typeof ob === "object") {
          addIf((ob as { column?: string }).column)
        }
      }
    }

    return sources
  }, [node.data])

  const isRunning = isExecutingProp || currentOutput?.status === "running"

  // ── Pin v3: async materialization ─────────────────────────────────────────
  const [isPinning, setIsPinning] = useState(false)

  const handlePin = useCallback(async () => {
    if (!currentOutput) return

    // Caminho v3 — referência DuckDB: materializa as linhas no backend
    if (currentOutput.output_reference && currentOutput.execution_id) {
      setIsPinning(true)
      try {
        const nodeId = currentOutput.output_reference.node_id
        const materialized = await materializePinFromBackend(
          currentOutput.execution_id,
          nodeId,
        )
        onUpdate(node.id, {
          ...(node.data as Record<string, unknown>),
          pinnedOutput: {
            __pinned_v: 3,
            rows: materialized.rows,
            columns: materialized.columns,
            row_count: materialized.row_count,
            total_rows: materialized.total_rows,
            truncated: materialized.truncated,
            schema_fingerprint: materialized.schema_fingerprint,
            pinned_at: new Date().toISOString(),
          },
        })
      } catch {
        // Silently ignore — toast not available here; user sees no change
      } finally {
        setIsPinning(false)
      }
      return
    }

    // Caminho inline: output já tem dados (legado ou nó sem DuckDB)
    if (!currentOutput.output) return
    const output = currentOutput.output
    const cols = Array.isArray(output.columns) ? (output.columns as string[]) : null
    const rows = Array.isArray(output.rows) ? (output.rows as Array<Record<string, unknown>>) : null
    if (cols && rows) {
      onUpdate(node.id, {
        ...(node.data as Record<string, unknown>),
        pinnedOutput: {
          __pinned_v: 3,
          rows,
          columns: cols,
          row_count: rows.length,
          total_rows: rows.length,
          truncated: false,
          schema_fingerprint: null,
          pinned_at: new Date().toISOString(),
        },
      })
    } else {
      // Output não-tabular (JSON puro): armazena legado v1
      onUpdate(node.id, {
        ...(node.data as Record<string, unknown>),
        pinnedOutput: output,
      })
    }
  }, [currentOutput, node.id, node.data, onUpdate])

  // ── Resizable panels ──────────────────────────────────────────────────────
  const containerRef = useRef<HTMLDivElement>(null)
  const [leftWidth, setLeftWidth] = useState<number | null>(() => loadSavedPanelWidths().left)
  const [centerWidth, setCenterWidth] = useState<number | null>(() => loadSavedPanelWidths().center)

  // Persiste larguras em localStorage — sobrevive a F5 e troca de no.
  useEffect(() => {
    saveSavedPanelWidths({ left: leftWidth, center: centerWidth })
  }, [leftWidth, centerWidth])

  const draggingRef = useRef<"left" | "right" | null>(null)
  const startXRef   = useRef(0)
  const startLRef   = useRef(0)
  const startCRef   = useRef(0)

  const leftRef   = useRef<HTMLDivElement>(null)
  const centerRef = useRef<HTMLDivElement>(null)

  // Clampa larguras salvas se o viewport encolheu desde a ultima sessao —
  // sem isso, larguras antigas extrapolam o container atual e quebram o
  // layout. Roda apenas no mount.
  useEffect(() => {
    if (!containerRef.current) return
    const totalW = containerRef.current.offsetWidth
    const maxBoth = totalW - PANEL_MIN_WIDTH - PANEL_HANDLE_TOTAL
    if (leftWidth !== null && centerWidth !== null) {
      if (leftWidth + centerWidth > maxBoth) {
        const ratio = maxBoth / (leftWidth + centerWidth)
        setLeftWidth(Math.max(PANEL_MIN_WIDTH, Math.floor(leftWidth * ratio)))
        setCenterWidth(Math.max(PANEL_MIN_WIDTH, Math.floor(centerWidth * ratio)))
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
      // Right panel = totalW - leftW - centerW - HANDLES. Para garantir que
      // ele nao encolha abaixo de MIN, calculamos o teto com base na largura
      // ATUAL do painel que nao esta sendo arrastado — so assim o lado oposto
      // mantem espaco suficiente.
      if (draggingRef.current === "left") {
        const currentCenter = centerRef.current?.offsetWidth ?? 0
        const maxLeft = totalW - currentCenter - PANEL_MIN_WIDTH - PANEL_HANDLE_TOTAL
        const newLeft = Math.max(
          PANEL_MIN_WIDTH,
          Math.min(startLRef.current + dx, Math.max(PANEL_MIN_WIDTH, maxLeft)),
        )
        setLeftWidth(newLeft)
      } else {
        const currentLeft = leftRef.current?.offsetWidth ?? 0
        const maxCenter = totalW - currentLeft - PANEL_MIN_WIDTH - PANEL_HANDLE_TOTAL
        const newCenter = Math.max(
          PANEL_MIN_WIDTH,
          Math.min(startCRef.current + dx, Math.max(PANEL_MIN_WIDTH, maxCenter)),
        )
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
            className="h-8 min-w-0 flex-1 rounded-md border border-transparent bg-transparent px-2 text-sm font-semibold text-foreground outline-none transition-colors placeholder:text-muted-foreground hover:border-input focus:border-input focus:ring-1 focus:ring-primary"
          />
          <div>
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
            style={leftWidth ? { width: leftWidth, flexShrink: 0, flexGrow: 0 } : { flex: 1 }}
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
            style={centerWidth ? { width: centerWidth, flexShrink: 0, flexGrow: 0 } : { flex: 1 }}
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
                  ? <><MorphLoader className="size-3" /> Executando…</>
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
              isPinning={isPinning}
              onPin={() => { void handlePin() }}
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
  // Aba global do painel — semelhante ao n8n: o seletor de visão
  // (Schema/Tabela/JSON) fica no topo e controla todos os upstreams ao
  // mesmo tempo. Em "schema" mostramos a lista de nós em accordion (ainda
  // o melhor formato pra ver schemas lado a lado). Em "table"/"json"
  // mostramos um seletor de nó + a visualização única do nó escolhido.
  const [tab, setTab] = useState<ViewTab>("schema")

  // Nó selecionado nas abas table/json. Inicia no primeiro upstream com
  // dados; se nenhum tiver, no primeiro da lista mesmo (depth=1 — mais
  // próximo ao nó atual).
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)

  useEffect(() => {
    if (
      selectedNodeId &&
      upstreamOutputs.some((u) => u.nodeId === selectedNodeId)
    ) {
      return
    }
    const firstWithData = upstreamOutputs.find((u) => u.output !== null)
    setSelectedNodeId(
      firstWithData?.nodeId ?? upstreamOutputs[0]?.nodeId ?? null,
    )
  }, [upstreamOutputs, selectedNodeId])

  const selectedUpstream =
    upstreamOutputs.find((u) => u.nodeId === selectedNodeId) ?? null

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
        <>
          {/* Top tabs (Schema/Tabela/JSON) — global pro painel inteiro */}
          <div className="flex h-8 shrink-0 items-center gap-1 border-b border-border px-2.5">
            <TabBtn
              active={tab === "schema"}
              onClick={() => setTab("schema")}
              icon={<List className="size-3" />}
              label="Schema"
            />
            <TabBtn
              active={tab === "table"}
              onClick={() => setTab("table")}
              icon={<Table2 className="size-3" />}
              label="Tabela"
            />
            <TabBtn
              active={tab === "json"}
              onClick={() => setTab("json")}
              icon={<Braces className="size-3" />}
              label="JSON"
            />
          </div>

          {tab === "schema" ? (
            // Schema: accordion com todos os upstreams (visão de comparação)
            <div className="min-h-0 flex-1 overflow-y-auto">
              {upstreamOutputs.map((up) => (
                <UpstreamAccordion key={up.nodeId} upstream={up} />
              ))}
            </div>
          ) : (
            // Tabela/JSON: seletor de nó no topo + visão única do selecionado
            <div className="flex min-h-0 flex-1 flex-col">
              <UpstreamNodeSelector
                upstreams={upstreamOutputs}
                selectedNodeId={selectedNodeId}
                onSelect={setSelectedNodeId}
              />
              <div className="flex min-h-0 flex-1 flex-col">
                {selectedUpstream && selectedUpstream.output ? (
                  <DataViewer
                    output={selectedUpstream.output}
                    sourceLabel={selectedUpstream.label}
                    sourceNodeType={selectedUpstream.nodeType}
                    sourceNodeId={selectedUpstream.nodeId}
                    executionId={selectedUpstream.executionId ?? null}
                    controlledTab={tab}
                    hideTabs
                  />
                ) : (
                  <div className="px-5 py-3 text-[11px] italic text-muted-foreground">
                    Execute os nós anteriores para ver os dados aqui.
                  </div>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

function UpstreamAccordion({ upstream }: { upstream: UpstreamOutput }) {
  const [open, setOpen] = useState((upstream.depth ?? 1) === 1)
  const NodeIcon = getNodeIcon(getNodeDefinition(upstream.nodeType)?.icon ?? "Database")
  const hasData = upstream.output !== null

  // Item count: prioriza row_count vindo do SSE lean (single source of truth
  // pós-execução); fallback pra rows.length quando o output ainda traz dados
  // inline (legado / inline_data).
  const inlineRowsLen = Array.isArray(upstream.output?.rows)
    ? (upstream.output!.rows as unknown[]).length
    : null
  const rowCount = typeof upstream.output?.row_count === "number"
    ? (upstream.output!.row_count as number)
    : inlineRowsLen
  const itemCountLabel = rowCount !== null
    ? `${rowCount} ${rowCount === 1 ? "item" : "itens"}`
    : null

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
        <span className="flex-1 break-words text-[12px] font-medium text-foreground">
          {upstream.label}
        </span>
        {hasData && itemCountLabel ? (
          <span className="shrink-0 text-[10px] text-muted-foreground tabular-nums">
            {itemCountLabel}
          </span>
        ) : null}
        {!hasData && (
          <span className="shrink-0 text-[10px] italic text-muted-foreground/50">sem dados</span>
        )}
      </button>

      {/* Content — força a aba ``schema`` e esconde tabs internas, já
          que o seletor global do InputPanel já decidiu que estamos em
          modo Schema. Mantém compatibilidade com chamadas standalone
          (executionPanel, output panel, etc.) que não passam estes props. */}
      {open && (
        hasData ? (
          <DataViewer
            output={upstream.output!}
            sourceLabel={upstream.label}
            sourceNodeType={upstream.nodeType}
            sourceNodeId={upstream.nodeId}
            executionId={upstream.executionId ?? null}
            controlledTab="schema"
            hideTabs
            hideSchemaHeader
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

function UpstreamNodeSelector({
  upstreams,
  selectedNodeId,
  onSelect,
}: {
  upstreams: UpstreamOutput[]
  selectedNodeId: string | null
  onSelect: (id: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  // Fecha ao clicar fora ou ESC.
  useEffect(() => {
    if (!open) return
    function handleMouseDown(e: MouseEvent) {
      // Cast via globalThis.Node — ``Node`` no escopo deste módulo está
      // sombreado pelo import do @xyflow/react, então usamos o tipo do DOM
      // explicitamente para o ``contains``.
      if (ref.current && !ref.current.contains(e.target as globalThis.Node)) setOpen(false)
    }
    function handleKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", handleMouseDown)
    document.addEventListener("keydown", handleKey)
    return () => {
      document.removeEventListener("mousedown", handleMouseDown)
      document.removeEventListener("keydown", handleKey)
    }
  }, [open])

  const selected = upstreams.find((u) => u.nodeId === selectedNodeId) ?? upstreams[0]
  const SelectedIcon = selected
    ? getNodeIcon(getNodeDefinition(selected.nodeType)?.icon ?? "Database")
    : null
  const itemCount = upstreams.length

  return (
    <div ref={ref} className="relative shrink-0 border-b border-border px-2.5 py-2">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 rounded-md border border-input bg-background px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-muted/40"
      >
        {SelectedIcon && (
          <SelectedIcon className="size-3.5 shrink-0 text-muted-foreground" />
        )}
        <span className="truncate font-medium text-foreground">
          {selected?.label ?? "Selecionar nó"}
        </span>
        <span className="ml-auto shrink-0 text-[10px] tabular-nums text-muted-foreground">
          {itemCount} {itemCount === 1 ? "nó" : "nós"}
        </span>
        <ChevronDown
          className={cn(
            "size-3 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </button>

      {open && (
        <div className="absolute left-2.5 right-2.5 top-full z-30 mt-1 max-h-72 overflow-y-auto rounded-lg border border-border bg-card p-1 shadow-lg">
          {upstreams.map((up) => {
            const Icon = getNodeIcon(
              getNodeDefinition(up.nodeType)?.icon ?? "Database",
            )
            const isActive = up.nodeId === selectedNodeId
            const depth = up.depth ?? 1
            const depthLabel =
              depth === 1 ? "1 nó atrás" : `${depth} nós atrás`
            return (
              <button
                key={up.nodeId}
                type="button"
                onClick={() => {
                  onSelect(up.nodeId)
                  setOpen(false)
                }}
                className={cn(
                  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors",
                  isActive ? "bg-accent text-foreground" : "hover:bg-muted/60",
                )}
              >
                <Icon className="size-3.5 shrink-0 text-muted-foreground" />
                <span className="truncate font-medium text-foreground">
                  {up.label}
                </span>
                <span className="ml-auto shrink-0 text-[10px] text-muted-foreground">
                  {depthLabel}
                </span>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ─── Output Panel (right) ────────────────────────────────────────────────────

function OutputPanel({
  currentOutput,
  onExecute,
  isPinned,
  isPinning,
  onPin,
  onUnpin,
}: {
  currentOutput: NodeExecState | null
  onExecute: () => void
  isPinned: boolean
  isPinning: boolean
  onPin: () => void
  onUnpin: () => void
}) {
  // Pin disponível tanto para output inline (legado) quanto para
  // output_reference (caminho lean atual). Sem ambos, não há nada pra fixar.
  const canPin = Boolean(currentOutput?.output || currentOutput?.output_reference)
    && !currentOutput?.is_pinned
    && !isPinning

  return (
    <div className="flex min-h-0 w-full flex-1 flex-col">
      {/* Header with pin button */}
      <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3">
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Output
        </span>
        {(isPinned || canPin || isPinning) && (
          <div className="flex items-center gap-1">
            {isPinned && (
              <button
                type="button"
                onClick={onUnpin}
                title="Liberar dados fixados"
                className="flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground/60 transition-colors hover:bg-muted hover:text-foreground"
              >
                <PinOff className="size-3" /> Liberar
              </button>
            )}
            {!isPinned && (
              <button
                type="button"
                onClick={onPin}
                disabled={isPinning || !canPin}
                title="Fixar dados (persiste entre sessões)"
                className={cn(
                  "flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[10px] font-medium transition-colors",
                  isPinning
                    ? "cursor-not-allowed text-muted-foreground/40"
                    : "text-muted-foreground/60 hover:bg-muted hover:text-foreground",
                )}
              >
                {isPinning
                  ? <><MorphLoader className="size-3" /> Fixando…</>
                  : <><Pin className="size-3" /> Fixar</>
                }
              </button>
            )}
          </div>
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

      {/* Pin parcial banner (v3 truncado) */}
      {isPinned && currentOutput?.pin_truncated && (
        <div className="flex items-center gap-2 border-b border-amber-500/30 bg-amber-500/10 px-3 py-1.5">
          <AlertTriangle className="size-3 shrink-0 text-amber-600" />
          <span className="text-[10px] text-amber-700 dark:text-amber-400">
            Pin parcial — apenas {currentOutput.row_count?.toLocaleString()} de {currentOutput.pin_total_rows?.toLocaleString()} linhas fixadas
          </span>
        </div>
      )}

      {currentOutput?.status === "running" ? (
        <div className="flex flex-1 items-center justify-center gap-2 text-xs text-muted-foreground">
          <MorphLoader className="size-3.5" />
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
          {(currentOutput.output || currentOutput.output_reference) && (
            <DataViewer
              output={currentOutput.output ?? { output_reference: currentOutput.output_reference }}
              executionId={currentOutput.execution_id}
            />
          )}
        </div>
      ) : currentOutput?.status === "error" ? (
        <div className="flex flex-col gap-2 p-3">
          <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-widest text-destructive">
            <XCircle className="size-3" />
            Erro
          </div>
          {currentOutput.error ? (
            <div className="rounded-md border border-red-500/20 bg-red-500/5 p-2.5 text-[11px] text-red-600 break-all dark:text-red-400">
              {currentOutput.error}
            </div>
          ) : (
            <div className="rounded-md border border-red-500/20 bg-red-500/5 p-2.5 text-[11px] text-red-600 dark:text-red-400">
              O nó falhou sem mensagem detalhada. Conecte o handle{" "}
              <code className="font-mono font-semibold">on_error</code> a outro
              nó (ex.: Saída do Fluxo) e re-execute para inspecionar o motivo
              por linha.
            </div>
          )}
          {/* Mesmo em erro, se houver branch on_error materializado, mostra
              os dados rejeitados — UX critica: usuario vê AGORA por que falhou
              sem precisar re-wirar o workflow. O preview API ja faz fallback
              ``{node_id}_on_error.duckdb`` quando o principal nao existe. */}
          {currentOutput.output_reference && currentOutput.execution_id && (
            <div className="mt-2 border-t border-border pt-2">
              <div className="mb-1.5 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                Branch on_error (linhas rejeitadas)
              </div>
              <DataViewer
                output={{ output_reference: currentOutput.output_reference }}
                executionId={currentOutput.execution_id}
              />
            </div>
          )}
        </div>
      ) : currentOutput?.output || currentOutput?.output_reference ? (
        <DataViewer
          output={currentOutput.output ?? { output_reference: currentOutput.output_reference }}
          executionId={currentOutput.execution_id}
        />
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
  | { kind: "execution_preview"; executionId: string; nodeId: string }

export function extractTableSource(
  output: Record<string, unknown>,
  executionId?: string | null,
): TableSource | null {
  if (Array.isArray(output.columns) && Array.isArray(output.rows)) {
    return {
      kind: "inline",
      columns: output.columns as string[],
      rows: output.rows as Array<Record<string, unknown>>,
    }
  }

  // Execution preview via output_reference (lean SSE format).
  if (executionId && output.output_reference && typeof output.output_reference === "object") {
    const ref = output.output_reference as Record<string, unknown>
    if (ref.storage_type === "duckdb") {
      // Preferimos path explícito quando vier — nós de transformação
      // (Mapper/Filter/Join) escrevem em arquivo .duckdb do upstream;
      // nesse caso ``{node_id}.duckdb`` não existe e o caminho convencional
      // ``/executions/.../nodes/{node_id}/preview`` retorna 404.
      if (
        typeof ref.database_path === "string" &&
        typeof ref.table_name === "string"
      ) {
        return {
          kind: "duckdb",
          databasePath: ref.database_path,
          tableName: ref.table_name,
          datasetName:
            typeof ref.dataset_name === "string" ? ref.dataset_name : null,
        }
      }
      if (typeof ref.node_id === "string") {
        return { kind: "execution_preview", executionId, nodeId: ref.node_id }
      }
    } else if (typeof ref.node_id === "string") {
      // Non-DuckDB reference (e.g. webhook/trigger nodes with storage_type "json")
      return { kind: "execution_preview", executionId, nodeId: ref.node_id }
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
  executionId,
  controlledTab,
  hideTabs = false,
  hideSchemaHeader = false,
}: {
  output: Record<string, unknown>
  sourceLabel?: string
  sourceNodeType?: string
  sourceNodeId?: string
  executionId?: string | null
  /** Quando definido, o DataViewer renderiza essa aba e ignora o estado
      interno — usado pelo InputPanel para centralizar o seletor de visão
      (Schema/Tabela/JSON) no topo do painel, estilo n8n. */
  controlledTab?: ViewTab
  /** Esconde a barra de abas interna. Combinado com ``controlledTab``,
      permite que o pai posicione as abas onde quiser. */
  hideTabs?: boolean
  /** Repassa para o ``SchemaView`` o flag ``hideRootHeader`` — usado quando
      o ancestral (ex.: ``UpstreamAccordion``) já mostra o cabeçalho do nó
      e o root da SchemaView duplicaria a mesma informação. */
  hideSchemaHeader?: boolean
}) {
  const [internalTab, setInternalTab] = useState<ViewTab>("schema")
  const tab = controlledTab ?? internalTab
  const setTab = controlledTab !== undefined ? () => {} : setInternalTab
  const [duckDbData, setDuckDbData] = useState<DuckDbPreviewResponse | NodePreviewResponse | null>(null)
  const [duckDbLoading, setDuckDbLoading] = useState(false)
  const [duckDbError, setDuckDbError] = useState<string | null>(null)

  const tableSource = useMemo(() => extractTableSource(output, executionId), [output, executionId])
  const isDuckDb = tableSource?.kind === "duckdb"
  const isExecPreview = tableSource?.kind === "execution_preview"
  const isInline = tableSource?.kind === "inline"

  // Reset remote fetch state when the source changes
  const duckDbKey = isDuckDb
    ? `duckdb::${tableSource.databasePath}::${tableSource.tableName}`
    : isExecPreview
    ? `exec::${tableSource.executionId}::${tableSource.nodeId}`
    : null
  useEffect(() => {
    setDuckDbData(null)
    setDuckDbError(null)
  }, [duckDbKey])

  // Auto-fetch preview (legacy DuckDB path or execution preview)
  useEffect(() => {
    if (duckDbData || duckDbLoading || duckDbError) return
    if (isDuckDb) {
      const src = tableSource as Extract<TableSource, { kind: "duckdb" }>
      setDuckDbLoading(true)
      fetchDuckdbPreview(src.databasePath, src.tableName, src.datasetName)
        .then((data) => setDuckDbData(data))
        .catch((err) => setDuckDbError(err?.message ?? "Erro ao carregar dados."))
        .finally(() => setDuckDbLoading(false))
    } else if (isExecPreview) {
      const src = tableSource as Extract<TableSource, { kind: "execution_preview" }>
      setDuckDbLoading(true)
      fetchNodePreview(src.executionId, src.nodeId)
        .then((data) => setDuckDbData(data))
        .catch((err) => setDuckDbError(err?.message ?? "Erro ao carregar prévia."))
        .finally(() => setDuckDbLoading(false))
    }
  }, [isDuckDb, isExecPreview, tableSource, duckDbData, duckDbLoading, duckDbError])

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
      ? ("total_rows" in duckDbData ? duckDbData.total_rows : duckDbData.row_count)
      : null
  const itemCountLabel = itemCount !== null
    ? `${itemCount}${("truncated" in (duckDbData ?? {})) && (duckDbData as DuckDbPreviewResponse)?.truncated ? " (prévia)" : ""} ${itemCount === 1 ? "item" : "itens"}`
    : null

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {/* Tabs (escondidas quando o pai controla via ``controlledTab``) */}
      {!hideTabs && (
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
              <MorphLoader className="size-3" />
            ) : (
              itemCountLabel
            )}
          </span>
        </div>
      )}

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
            hideRootHeader={hideSchemaHeader}
          />
        ) : tab === "table" ? (
          duckDbLoading ? (
            <div className="flex h-full items-center justify-center gap-2 text-xs text-muted-foreground">
              <MorphLoader className="size-4" />
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
  hideRootHeader = false,
}: {
  columns?: string[]
  sampleRow: Record<string, unknown> | null
  output: Record<string, unknown>
  sourceLabel?: string
  sourceNodeType?: string
  sourceNodeId?: string
  /** Suprime o cabeçalho-raiz colapsável (label + ícone + contagem) — usado
      pelo InputPanel quando o pai já provê seu próprio header de upstream
      e o duplicaria. Mantido como opt-in para não mexer em chamadas
      standalone (OutputPanel, ExecutionPanel) onde o header é necessário. */
  hideRootHeader?: boolean
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
        {/* Root node: collapsible (omitted when ancestor already shows label) */}
        {!hideRootHeader && (
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
        )}

        {/* Fields */}
        {(expanded || hideRootHeader) && (
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

// ── MiniTable: tabela compacta com resize/autofit/menu de contexto ─────────

const MINI_DEFAULT_COL_WIDTH = 160
const MINI_MIN_COL_WIDTH = 60
const MINI_MAX_COL_WIDTH = 600
// Fonte usada para medir colunas via canvas — bate com `text-xs` do <table>
// abaixo. Sem isso o autofit erra em umas casas decimais e corta a última
// letra da coluna mais larga.
const MINI_TABLE_FONT = '12px ui-monospace, SFMono-Regular, "Roboto Mono", Menlo, monospace'
const MINI_COL_PADDING = 28

function miniCellText(value: unknown): string {
  if (value === null || value === undefined) return "null"
  return String(value)
}

function MiniTable({
  columns,
  rows,
}: {
  columns: string[]
  rows: Array<Record<string, unknown>>
}) {
  const [widths, setWidths] = useState<Record<string, number>>({})
  const [menu, setMenu] = useState<{ x: number; y: number; col: string } | null>(null)

  const getWidth = (col: string) => widths[col] ?? MINI_DEFAULT_COL_WIDTH

  const measureCol = useCallback(
    (col: string): number => {
      if (typeof document === "undefined") return MINI_DEFAULT_COL_WIDTH
      const canvas = document.createElement("canvas")
      const ctx = canvas.getContext("2d")
      if (!ctx) return MINI_DEFAULT_COL_WIDTH
      ctx.font = MINI_TABLE_FONT
      let max = ctx.measureText(col).width
      for (const row of rows) {
        const w = ctx.measureText(miniCellText(row[col])).width
        if (w > max) max = w
      }
      return Math.max(
        MINI_MIN_COL_WIDTH,
        Math.min(MINI_MAX_COL_WIDTH, Math.ceil(max + MINI_COL_PADDING)),
      )
    },
    [rows],
  )

  const autofitColumn = (col: string) => {
    setWidths((prev) => ({ ...prev, [col]: measureCol(col) }))
  }
  const autofitAll = () => {
    const next: Record<string, number> = {}
    for (const c of columns) next[c] = measureCol(c)
    setWidths(next)
  }
  const resetAll = () => setWidths({})

  const onResizeMouseDown = (e: React.MouseEvent, col: string) => {
    e.preventDefault()
    e.stopPropagation()
    const startX = e.clientX
    const startW = getWidth(col)
    const onMove = (ev: MouseEvent) => {
      const delta = ev.clientX - startX
      const next = Math.max(MINI_MIN_COL_WIDTH, Math.min(MINI_MAX_COL_WIDTH, startW + delta))
      setWidths((prev) => ({ ...prev, [col]: next }))
    }
    const onUp = () => {
      window.removeEventListener("mousemove", onMove)
      window.removeEventListener("mouseup", onUp)
    }
    window.addEventListener("mousemove", onMove)
    window.addEventListener("mouseup", onUp)
  }

  // Fecha menu de contexto em mousedown global ou Esc.
  useEffect(() => {
    if (!menu) return
    const close = () => setMenu(null)
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close()
    }
    window.addEventListener("mousedown", close)
    window.addEventListener("keydown", onKey)
    return () => {
      window.removeEventListener("mousedown", close)
      window.removeEventListener("keydown", onKey)
    }
  }, [menu])

  if (rows.length === 0) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-muted-foreground">
        Nenhuma linha.
      </div>
    )
  }

  return (
    <>
      <table className="border-separate border-spacing-0 text-xs" style={{ tableLayout: "fixed" }}>
        <colgroup>
          <col style={{ width: 36 }} />
          {columns.map((col) => (
            <col key={col} style={{ width: getWidth(col) }} />
          ))}
        </colgroup>
        <thead className="sticky top-0 z-10">
          <tr className="bg-muted/80 backdrop-blur-sm">
            <th className="sticky left-0 z-20 border-b border-r border-border bg-muted/80 px-1.5 py-1.5 text-center font-semibold text-muted-foreground backdrop-blur-sm">
              #
            </th>
            {columns.map((col) => (
              <th
                key={col}
                style={{ width: getWidth(col) }}
                className="border-b border-r border-border bg-muted/80 p-0 text-left font-semibold text-muted-foreground select-none last:border-r-0"
              >
                {/* Wrapper flex em vez de <th> direto: <th> é table-cell,
                    cuja capacidade de servir como containing block para
                    elementos absolute-positioned é irregular entre
                    browsers. O div garante o contexto. */}
                <div className="flex items-stretch">
                  <button
                    type="button"
                    onContextMenu={(e) => {
                      e.preventDefault()
                      setMenu({ x: e.clientX, y: e.clientY, col })
                    }}
                    onDoubleClick={() => autofitColumn(col)}
                    className="min-w-0 flex-1 truncate px-3 py-1.5 text-left"
                    title="Arraste a borda · duplo-clique auto-ajusta · botão direito para mais opções"
                  >
                    {col}
                  </button>
                  <div
                    onMouseDown={(e) => onResizeMouseDown(e, col)}
                    onDoubleClick={(e) => {
                      e.stopPropagation()
                      autofitColumn(col)
                    }}
                    className="w-1.5 shrink-0 cursor-col-resize bg-border/40 transition-colors hover:bg-primary"
                    aria-hidden
                  />
                </div>
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
                  style={{ width: getWidth(col), maxWidth: getWidth(col) }}
                  className="overflow-hidden border-b border-r border-border/40 px-3 py-1 text-ellipsis whitespace-nowrap text-foreground last:border-r-0"
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

      {menu && (
        <div
          onMouseDown={(e) => e.stopPropagation()}
          style={{ left: menu.x, top: menu.y }}
          className="fixed z-50 min-w-[200px] rounded-md border border-border bg-popover py-1 text-xs shadow-lg"
          role="menu"
        >
          <button
            type="button"
            onClick={() => { autofitColumn(menu.col); setMenu(null) }}
            className="block w-full px-3 py-1.5 text-left hover:bg-accent"
          >
            Ajustar a esta coluna
          </button>
          <button
            type="button"
            onClick={() => { autofitAll(); setMenu(null) }}
            className="block w-full px-3 py-1.5 text-left hover:bg-accent"
          >
            Ajustar todas as colunas
          </button>
          <div className="my-1 h-px bg-border" />
          <button
            type="button"
            onClick={() => { resetAll(); setMenu(null) }}
            className="block w-full px-3 py-1.5 text-left hover:bg-accent"
          >
            Resetar larguras
          </button>
        </div>
      )}
    </>
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
