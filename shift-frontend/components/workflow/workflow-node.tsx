"use client"

import { Fragment, memo, useCallback, useState } from "react"
import { Handle, NodeToolbar, Position, useReactFlow, type NodeProps } from "@xyflow/react"
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Copy,
  Loader2,
  PencilLine,
  Play,
  Power,
  RefreshCw,
  Trash2,
  XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { getNodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import { useNodeExecution } from "@/lib/workflow/execution-context"
import { useNodeActions } from "@/lib/workflow/node-actions-context"

const VAR_REF_RE = /\{\{\s*vars\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}/g

function countVarRefs(data: Record<string, unknown>): number {
  const text = JSON.stringify(data)
  return (text.match(VAR_REF_RE) ?? []).length
}

// ─── Color themes ──────────────────────────────────────────────────────────────

const themes: Record<
  string,
  {
    iconBg: string
    iconColor: string
    border: string
    handleColor: string
    ring: string
  }
> = {
  amber: {
    iconBg:      "bg-amber-100 dark:bg-amber-500/20",
    iconColor:   "text-amber-600 dark:text-amber-400",
    border:      "border-amber-200 dark:border-amber-500/30",
    handleColor: "!bg-amber-500",
    ring:        "ring-amber-400/50",
  },
  blue: {
    iconBg:      "bg-blue-100 dark:bg-blue-500/20",
    iconColor:   "text-blue-600 dark:text-blue-400",
    border:      "border-blue-200 dark:border-blue-500/30",
    handleColor: "!bg-blue-500",
    ring:        "ring-blue-400/50",
  },
  violet: {
    iconBg:      "bg-violet-100 dark:bg-violet-500/20",
    iconColor:   "text-violet-600 dark:text-violet-400",
    border:      "border-violet-200 dark:border-violet-500/30",
    handleColor: "!bg-violet-500",
    ring:        "ring-violet-400/50",
  },
  emerald: {
    iconBg:      "bg-emerald-100 dark:bg-emerald-500/20",
    iconColor:   "text-emerald-600 dark:text-emerald-400",
    border:      "border-emerald-200 dark:border-emerald-500/30",
    handleColor: "!bg-emerald-500",
    ring:        "ring-emerald-400/50",
  },
  pink: {
    iconBg:      "bg-pink-100 dark:bg-pink-500/20",
    iconColor:   "text-pink-600 dark:text-pink-400",
    border:      "border-pink-200 dark:border-pink-500/30",
    handleColor: "!bg-pink-500",
    ring:        "ring-pink-400/50",
  },
  orange: {
    iconBg:      "bg-orange-100 dark:bg-orange-500/20",
    iconColor:   "text-orange-600 dark:text-orange-400",
    border:      "border-orange-200 dark:border-orange-500/30",
    handleColor: "!bg-orange-500",
    ring:        "ring-orange-400/50",
  },
  slate: {
    iconBg:      "bg-slate-100 dark:bg-slate-500/20",
    iconColor:   "text-slate-600 dark:text-slate-300",
    border:      "border-slate-200 dark:border-slate-500/30",
    handleColor: "!bg-slate-500",
    ring:        "ring-slate-400/50",
  },
  red: {
    iconBg:      "bg-red-100 dark:bg-red-500/20",
    iconColor:   "text-red-600 dark:text-red-400",
    border:      "border-red-200 dark:border-red-500/30",
    handleColor: "!bg-red-500",
    ring:        "ring-red-400/50",
  },
}

// ─── Config summary helper ─────────────────────────────────────────────────────

interface SummaryRow {
  label: string
  value: string
  badge?: boolean
}

function getNodeSummaryRows(type: string, data: Record<string, unknown>): SummaryRow[] {
  const s = (v: unknown) => (v != null && String(v).trim() ? String(v).trim() : null)

  // Connection: prefer saved name, fallback to truncated UUID
  const connDisplay = (id: unknown, name: unknown): string | null => {
    const n = s(name)
    if (n) return n
    const raw = s(id)
    if (!raw) return null
    return raw.length > 13 ? `${raw.slice(0, 8)}…` : raw
  }

  switch (type) {
    case "sql_database":
    case "polling": {
      const rows: SummaryRow[] = []
      const conn = connDisplay(data.connection_id, data.connection_name)
      if (conn) rows.push({ label: "Conexão", value: conn, badge: true })
      // query is rendered as a separate code block — not here
      return rows
    }
    case "cron":
      return s(data.cron_expression)
        ? [{ label: "Expressão", value: s(data.cron_expression)!, badge: true }]
        : []
    case "http_request":
    case "api_input": {
      const rows: SummaryRow[] = []
      if (s(data.method)) rows.push({ label: "Método", value: s(data.method)!, badge: true })
      if (s(data.url))    rows.push({ label: "URL", value: s(data.url)! })
      return rows
    }
    case "csv_input":
    case "excel_input":
      return s(data.url) ? [{ label: "Arquivo", value: s(data.url)! }] : []
    case "loadNode": {
      const rows: SummaryRow[] = []
      const conn = connDisplay(data.connection_id, data.connection_name)
      if (conn) rows.push({ label: "Conexão", value: conn, badge: true })
      if (s(data.target_table))      rows.push({ label: "Tabela", value: s(data.target_table)! })
      if (s(data.write_disposition)) rows.push({ label: "Modo",   value: s(data.write_disposition)!, badge: true })
      return rows
    }
    case "filter": {
      const n = Array.isArray(data.conditions) ? data.conditions.length : 0
      return n > 0 ? [{ label: "Condições", value: `${n} regra${n !== 1 ? "s" : ""}`, badge: true }] : []
    }
    case "mapper": {
      const n = Array.isArray(data.mappings) ? data.mappings.length : 0
      return n > 0 ? [{ label: "Campos", value: `${n} mapeamento${n !== 1 ? "s" : ""}`, badge: true }] : []
    }
    case "if_node": {
      const n = Array.isArray(data.conditions) ? data.conditions.length : 0
      return n > 0 ? [{ label: "Condições", value: `${n} regra${n !== 1 ? "s" : ""}`, badge: true }] : []
    }
    case "switch_node": {
      const field = s(data.switch_field)
      const nc = Array.isArray(data.cases) ? data.cases.length : 0
      const rows: SummaryRow[] = []
      if (field) rows.push({ label: "Campo", value: field, badge: true })
      if (nc > 0) rows.push({ label: "Cases", value: `${nc} saída${nc !== 1 ? "s" : ""}`, badge: true })
      return rows
    }
    case "aiNode":
      return s(data.model_name) ? [{ label: "Modelo", value: s(data.model_name)!, badge: true }] : []
    default:
      return []
  }
}

const sourceHandleBaseClass =
  "!size-2.5 !right-0 !rounded-full !border-[1.5px] !border-slate-400 dark:!border-slate-500 !bg-background !shadow-none !transition-all !duration-200 !opacity-0 group-hover/node:!opacity-100 hover:!scale-125 hover:!border-primary"

function BranchSourceHandle({
  id,
  top,
  colorClass,
  label,
  labelClass,
}: {
  id: string
  top: string
  colorClass: string
  label: string
  labelClass: string
}) {
  return (
    <Handle
      type="source"
      position={Position.Right}
      id={id}
      style={{ top }}
      className={cn(sourceHandleBaseClass, colorClass)}
      title={label}
    />
  )
}

function LegacySourceHandle() {
  return (
    <Handle
      type="source"
      position={Position.Right}
      style={{ top: "50%" }}
      className="!size-2 !-right-1 !border-0 !bg-transparent !opacity-0 !pointer-events-none"
    />
  )
}

// ─── Node component ────────────────────────────────────────────────────────────

function WorkflowNodeComponent({ id, data, selected, type }: NodeProps) {
  const { deleteElements, setNodes, getNode } = useReactFlow()
  const { onExecuteNode } = useNodeActions()
  const [hovered, setHovered] = useState(false)

  const definition  = getNodeDefinition(type ?? "")
  const nodeData    = data as Record<string, unknown>
  const isPending   = nodeData.__pending === true
  const customIcon  = typeof nodeData.icon === "string" ? nodeData.icon : null
  const customColor = typeof nodeData.color === "string" && nodeData.color.trim() !== "" ? nodeData.color : null
  const theme       = themes[definition?.color ?? "blue"] ?? themes.blue
  const Icon        = getNodeIcon(customIcon ?? definition?.icon ?? "Database")
  const label       = nodeData.label as string | undefined
  const enabled     = nodeData.enabled !== false          // default: enabled
  const retryPolicy = nodeData.retry_policy as
    | { max_attempts?: number; backoff_strategy?: string }
    | null
    | undefined
  const retryActive =
    retryPolicy != null &&
    typeof retryPolicy.max_attempts === "number" &&
    retryPolicy.max_attempts > 1
  const execState   = useNodeExecution(id)
  const summaryRows = getNodeSummaryRows(type ?? "", nodeData)
  const varRefCount = countVarRefs(nodeData)

  // Code/SQL block (shown below summary)
  const codeContent = (() => {
    if (type === "sql_database" || type === "polling") {
      const q = (nodeData.query as string | undefined)?.trim()
      return q || null
    }
    if (type === "code") {
      const c = (nodeData.code as string | undefined)?.trim()
      return c || null
    }
    return null
  })()

  // Execution-state border override
  const execBorder =
    execState?.status === "running" ? "!border-amber-400 shadow-amber-300/40 shadow-lg"
    : execState?.status === "success" ? "!border-emerald-400 shadow-emerald-300/30 shadow-md"
    : execState?.status === "handled_error" ? "!border-rose-400 shadow-rose-300/30 shadow-md"
    : execState?.status === "error"   ? "!border-red-500 shadow-red-400/30 shadow-lg"
    : ""

  // ── Inline label edit ────────────────────────────────────────────────────
  const handleLabelChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
      setNodes((nds) =>
        nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, label: e.target.value } } : n)),
      )
    },
    [id, setNodes],
  )

  // ── Context menu actions ─────────────────────────────────────────────────
  const handleToggleEnabled = useCallback(() => {
    setNodes((nds) =>
      nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, enabled: !enabled } } : n)),
    )
  }, [id, enabled, setNodes])

  const handleExecute = useCallback(() => {
    onExecuteNode(id)
  }, [id, onExecuteNode])

  const handleDelete = useCallback(() => {
    deleteElements({ nodes: [{ id }] })
  }, [id, deleteElements])

  const handleDuplicate = useCallback(() => {
    const node = getNode(id)
    if (!node) return
    const newId = `node_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`
    setNodes((nds) => [
      ...nds,
      {
        ...node,
        id: newId,
        selected: false,
        position: { x: node.position.x + 40, y: node.position.y + 40 },
      },
    ])
  }, [id, getNode, setNodes])

  return (
    <div
      className={cn(
        "group/node relative min-w-[96px] rounded-2xl border bg-card shadow-md transition-all duration-200",
        hovered && "shadow-xl shadow-black/10 dark:shadow-black/40",
        isPending
          ? "border-dashed border-2 border-violet-400 dark:border-violet-500 opacity-60"
          : theme.border,
        !isPending && execBorder,
        selected && `ring-2 ring-offset-2 ring-offset-background ${isPending ? "ring-violet-400/60" : theme.ring}`,
        !enabled && "opacity-50",
      )}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      {/* ── Floating action toolbar ── */}
      <NodeToolbar isVisible={hovered || selected} position={Position.Top} offset={6}>
        <div className="flex items-center gap-0.5 rounded-lg border border-border bg-card px-1.5 py-1 shadow-lg">
          <button
            type="button"
            onClick={handleExecute}
            title="Executar"
            className="rounded p-1 text-primary transition-colors hover:bg-muted"
          >
            <Play className="size-3" />
          </button>
          <button
            type="button"
            onClick={handleToggleEnabled}
            title={enabled ? "Desativar" : "Ativar"}
            className="rounded p-1 transition-colors hover:bg-muted"
          >
            <Power className={cn("size-3", enabled ? "text-muted-foreground" : "text-amber-500")} />
          </button>
          <button
            type="button"
            onClick={handleDuplicate}
            title="Duplicar"
            className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted"
          >
            <Copy className="size-3" />
          </button>
          <div className="mx-0.5 h-3 w-px bg-border" />
          <button
            type="button"
            onClick={handleDelete}
            title="Excluir"
            className="rounded p-1 text-destructive transition-colors hover:bg-red-50 dark:hover:bg-red-950/30"
          >
            <Trash2 className="size-3" />
          </button>
        </div>
      </NodeToolbar>

      {/* Ghost badge */}
      {isPending && (
          <span className="absolute -top-2 -right-2 z-10 flex items-center gap-0.5 rounded-full bg-violet-500 px-1.5 py-0.5 text-[9px] font-bold text-white shadow-sm">
            <Bot className="size-2.5" />
            IA
          </span>
        )}

        {/* Target handle */}
        {definition?.category !== "trigger" && (
          <Handle
            type="target"
            position={Position.Left}
            className="!size-2.5 !left-0 !rounded-full !border-[1.5px] !border-slate-400 dark:!border-slate-500 !bg-background !shadow-none !transition-all !duration-200 !opacity-0 group-hover/node:!opacity-100 hover:!scale-125 hover:!border-primary"
          />
        )}

        {/* ── Header: always compact, info only on hover ── */}
        <div className="flex items-center gap-2.5 px-3 py-2.5">
          <div className="relative shrink-0">
            <div
              className={cn(
                "flex size-8 items-center justify-center rounded-xl transition-all",
                !customColor && theme.iconBg,
                execState?.status === "running" && "animate-pulse",
              )}
              style={customColor ? { backgroundColor: `${customColor}20`, color: customColor } : undefined}
            >
              <Icon className={cn("size-4", !customColor && theme.iconColor)} />
            </div>
            {execState?.status === "running" && (
              <span className="absolute -bottom-1 -right-1 flex size-4 items-center justify-center rounded-full border-2 border-background bg-amber-400">
                <Loader2 className="size-2.5 animate-spin text-white" />
              </span>
            )}
            {execState?.status === "success" && (
              <span className="absolute -bottom-1 -right-1 flex size-4 items-center justify-center rounded-full border-2 border-background bg-emerald-500">
                <CheckCircle2 className="size-2.5 text-white" />
              </span>
            )}
            {execState?.status === "handled_error" && (
              <span className="absolute -bottom-1 -right-1 flex size-4 items-center justify-center rounded-full border-2 border-background bg-rose-500">
                <AlertTriangle className="size-2.5 text-white" />
              </span>
            )}
            {execState?.status === "error" && (
              <span className="absolute -bottom-1 -right-1 flex size-4 items-center justify-center rounded-full border-2 border-background bg-red-500">
                <XCircle className="size-2.5 text-white" />
              </span>
            )}
          </div>

          {/* Exec status + badges — hover only, only when there's something to show */}
          {hovered && (!enabled || execState?.status || retryActive || varRefCount > 0) && (
            <div className="min-w-0 flex-1">
              {(!enabled || execState?.status) && (
                <p className="truncate text-[11px] leading-tight text-muted-foreground">
                  {!enabled
                    ? "desativado"
                    : execState?.status === "running"
                    ? "executando…"
                    : execState?.status === "success" &&
                      typeof execState.output?.row_count === "number"
                    ? `${execState.output.row_count} linhas · ${execState.duration_ms}ms`
                    : execState?.status === "error"
                    ? "erro na execução"
                    : null}
                </p>
              )}
              {(retryActive || varRefCount > 0) && (
                <div className="mt-0.5 flex items-center gap-1">
                  {retryActive && (
                    <span
                      className="flex items-center gap-0.5 rounded bg-sky-500/10 px-1 py-0.5 text-[9px] font-medium text-sky-600 dark:text-sky-400"
                      title={`Retry: ${retryPolicy?.max_attempts} tentativas (${retryPolicy?.backoff_strategy ?? "none"})`}
                    >
                      <RefreshCw className="size-2.5" />
                      {retryPolicy?.max_attempts}x
                    </span>
                  )}
                  {varRefCount > 0 && (
                    <span
                      className="flex items-center gap-0.5 rounded bg-violet-500/10 px-1 py-0.5 text-[9px] font-medium text-violet-600 dark:text-violet-400"
                      title={`${varRefCount} referência${varRefCount > 1 ? "s" : ""} a variável`}
                    >
                      {"{}"}
                      {varRefCount}
                    </span>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* ── Config summary rows (hover only) ── */}
        <div
          className={cn(
            "overflow-hidden transition-all duration-200",
            hovered && summaryRows.length > 0 ? "w-[180px] max-h-48" : "max-h-0",
          )}
        >
          <div className="mx-3 mb-2 rounded-lg border border-border/50 bg-muted/30 px-2.5 py-2">
            <div className="grid grid-cols-[52px_1fr] items-center gap-y-1.5">
              {summaryRows.map((row) => (
                <Fragment key={row.label}>
                  <span className="text-[10px] font-medium text-muted-foreground">{row.label}</span>
                  <div className="flex justify-end">
                    {row.badge ? (
                      <span className="inline-flex items-center rounded border border-border/60 bg-background px-1.5 py-0.5 font-mono text-[10px] font-semibold text-foreground">
                        {row.value}
                      </span>
                    ) : (
                      <span className="max-w-[88px] truncate text-right text-[10px] text-foreground">
                        {row.value}
                      </span>
                    )}
                  </div>
                </Fragment>
              ))}
            </div>
          </div>
        </div>

        {/* ── Code / SQL dark block (hover only) ── */}
        <div
          className={cn(
            "overflow-hidden transition-all duration-200",
            hovered && codeContent ? "w-[180px] max-h-40" : "max-h-0",
          )}
        >
          <div className="mx-3 mb-3 overflow-hidden rounded-lg bg-[#1a1b26] px-2.5 py-2">
            <p className="break-all font-mono text-[10px] leading-relaxed text-[#a5b4fc] line-clamp-3">
              {codeContent}
            </p>
          </div>
        </div>

        {/* ── Source handles ── */}
        {(() => {
          if (definition?.type === "if_node") {
            return (
              <>
                <BranchSourceHandle id="true" top="38%" colorClass="!border-emerald-500 hover:!border-emerald-600" label="V" labelClass="text-emerald-500" />
                <BranchSourceHandle id="false" top="62%" colorClass="!border-orange-500 hover:!border-orange-600" label="F" labelClass="text-orange-500" />
              </>
            )
          }
          if (definition?.type === "switch_node") {
            const cases: { label: string }[] = Array.isArray(nodeData.cases) ? (nodeData.cases as { label: string }[]) : []
            const handleIds = [...cases.map((c) => c.label).filter(Boolean), "default"]
            const count = handleIds.length || 1
            return (
              <>
                <LegacySourceHandle />
                {handleIds.map((hId, idx) => {
                  const pct = count === 1 ? 38 : 18 + (idx * 44) / Math.max(count - 1, 1)
                  return (
                    <Fragment key={hId}>
                      <Handle
                        type="source"
                        position={Position.Right}
                        id={hId}
                        style={{ top: `${pct}%` }}
                        className={sourceHandleBaseClass}
                      />
                      <span
                        className="pointer-events-none absolute text-[8px] font-semibold text-muted-foreground"
                        style={{ right: 10, top: `${pct}%`, transform: "translateY(-50%)" }}
                      >
                        {hId.length > 6 ? hId.slice(0, 6) + "…" : hId}
                      </span>
                    </Fragment>
                  )
                })}
              </>
            )
          }
          return (
            <>
              <LegacySourceHandle />
              <BranchSourceHandle
                id="success"
                top={definition?.errorHandle ? "36%" : "50%"}
                colorClass={definition?.errorHandle ? "!border-emerald-500 hover:!border-emerald-600" : ""}
                label="OK"
                labelClass="text-emerald-500"
              />
              {definition?.errorHandle && (
                <BranchSourceHandle id="on_error" top="64%" colorClass="!border-red-500 hover:!border-red-600" label="ERR" labelClass="text-red-500" />
              )}
            </>
          )
        })()}

      {/* ── External label + description (absolute, excluded from bbox) ── */}
      <div className="absolute left-1/2 top-full mt-1.5 flex w-[180px] -translate-x-1/2 flex-col items-center gap-0.5 px-1">
        <div className="flex w-full items-start justify-center gap-1">
          <textarea
            value={label ?? definition?.label ?? type ?? ""}
            onChange={(e) => {
              handleLabelChange(e)
              e.currentTarget.style.height = "auto"
              e.currentTarget.style.height = `${e.currentTarget.scrollHeight}px`
            }}
            onInput={(e) => {
              e.currentTarget.style.height = "auto"
              e.currentTarget.style.height = `${e.currentTarget.scrollHeight}px`
            }}
            onClick={(e) => e.stopPropagation()}
            rows={1}
            className="nodrag nopan min-w-0 flex-1 resize-none overflow-hidden break-words bg-transparent text-center text-[12px] font-semibold leading-tight text-foreground outline-none placeholder:text-muted-foreground"
            placeholder="Nome do nó"
          />
          <PencilLine className="mt-0.5 size-2.5 shrink-0 text-muted-foreground/40 opacity-0 transition-opacity group-hover/node:opacity-100" />
        </div>
        {definition?.description && (
          <p className="w-full break-words text-center text-[10px] text-muted-foreground">
            {definition.description}
          </p>
        )}
      </div>
    </div>
  )
}

export const WorkflowNode = memo(WorkflowNodeComponent)
