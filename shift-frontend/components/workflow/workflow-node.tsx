"use client"

import { Fragment, memo, useCallback, useEffect, useRef, useState } from "react"
import { Handle, Position, useReactFlow, type NodeProps } from "@xyflow/react"
import {
  CheckCircle2,
  Copy,
  Loader2,
  MoreHorizontal,
  PencilLine,
  Play,
  Power,
  Trash2,
  XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { getNodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import { useNodeExecution } from "@/lib/workflow/execution-context"
import { useNodeActions } from "@/lib/workflow/node-actions-context"

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

// ─── Node component ────────────────────────────────────────────────────────────

function WorkflowNodeComponent({ id, data, selected, type }: NodeProps) {
  const { deleteElements, setNodes, getNode } = useReactFlow()
  const { onExecuteNode } = useNodeActions()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close menu when clicking outside (capture phase — works inside React Flow canvas)
  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", onDown, true)
    return () => document.removeEventListener("mousedown", onDown, true)
  }, [menuOpen])

  const definition  = getNodeDefinition(type ?? "")
  const theme       = themes[definition?.color ?? "blue"] ?? themes.blue
  const Icon        = getNodeIcon(definition?.icon ?? "Database")
  const nodeData    = data as Record<string, unknown>
  const label       = nodeData.label as string | undefined
  const enabled     = nodeData.enabled !== false          // default: enabled
  const execState   = useNodeExecution(id)
  const summaryRows = getNodeSummaryRows(type ?? "", nodeData)

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
    : execState?.status === "error"   ? "!border-red-500 shadow-red-400/30 shadow-lg"
    : ""

  // ── Inline label edit ────────────────────────────────────────────────────
  const handleLabelChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
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
    setMenuOpen(false)
  }, [id, enabled, setNodes])

  const handleExecute = useCallback(() => {
    setMenuOpen(false)
    onExecuteNode(id)
  }, [id, onExecuteNode])

  const handleDelete = useCallback(() => {
    deleteElements({ nodes: [{ id }] })
    setMenuOpen(false)
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
    setMenuOpen(false)
  }, [id, getNode, setNodes])

  return (
    <div
      className={cn(
        "group/node relative w-[240px] rounded-2xl border bg-card shadow-md transition-all duration-200",
        theme.border,
        execBorder,
        selected && `ring-2 ring-offset-2 ring-offset-background ${theme.ring}`,
        !enabled && "opacity-50",
      )}
    >
      {/* ── Target handle (left) ── */}
      {definition?.category !== "trigger" && (
        <Handle
          type="target"
          position={Position.Left}
          className={cn(
            "!size-3.5 !-left-2 !rounded-full !border-2 !border-background !transition-transform hover:!scale-125",
            theme.handleColor,
          )}
        />
      )}

      {/* ── Header ── */}
      <div className="flex items-center gap-2.5 p-3">
        {/* Icon with execution badge */}
        <div className="relative shrink-0">
          <div
            className={cn(
              "flex size-9 items-center justify-center rounded-xl transition-all",
              theme.iconBg,
              execState?.status === "running" && "animate-pulse",
            )}
          >
            <Icon className={cn("size-4", theme.iconColor)} />
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
          {execState?.status === "error" && (
            <span className="absolute -bottom-1 -right-1 flex size-4 items-center justify-center rounded-full border-2 border-background bg-red-500">
              <XCircle className="size-2.5 text-white" />
            </span>
          )}
        </div>

        {/* Inline-editable label + subtitle */}
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <input
              value={label ?? definition?.label ?? type ?? ""}
              onChange={handleLabelChange}
              onClick={(e) => e.stopPropagation()}
              className="nodrag nopan min-w-0 flex-1 truncate bg-transparent text-[13px] font-bold leading-tight text-foreground outline-none placeholder:text-muted-foreground"
              placeholder="Nome do nó"
            />
            <PencilLine
              className="size-2.5 shrink-0 text-muted-foreground/40 opacity-0 transition-opacity group-hover/node:opacity-100"
            />
          </div>
          <p className="mt-0.5 truncate text-[11px] leading-tight text-muted-foreground">
            {!enabled
              ? "desativado"
              : execState?.status === "running"
              ? "executando…"
              : execState?.status === "success" &&
                typeof execState.output?.row_count === "number"
              ? `${execState.output.row_count} linhas · ${execState.duration_ms}ms`
              : execState?.status === "error"
              ? "erro na execução"
              : definition?.description ?? "Nó customizado"}
          </p>
        </div>

        {/* ── "..." context menu ── */}
        <div ref={menuRef} className="relative shrink-0">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation()
              setMenuOpen((v) => !v)
            }}
            className={cn(
              "rounded p-1 text-muted-foreground transition-all",
              menuOpen
                ? "bg-muted text-foreground"
                : "opacity-0 hover:bg-muted group-hover/node:opacity-60 hover:!opacity-100",
            )}
            aria-label="Opções do nó"
          >
            <MoreHorizontal className="size-3.5" />
          </button>

          {menuOpen && (
            <div className="absolute right-0 top-full z-40 mt-1 w-48 overflow-hidden rounded-xl border border-border bg-card py-1 shadow-xl">
              {/* Execute */}
              <button
                type="button"
                onClick={handleExecute}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs font-medium text-foreground transition-colors hover:bg-muted"
              >
                <Play className="size-3.5 text-primary" />
                Executar este nó
              </button>

              <div className="my-1 h-px bg-border" />

              {/* Duplicate */}
              <button
                type="button"
                onClick={handleDuplicate}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs font-medium text-foreground transition-colors hover:bg-muted"
              >
                <Copy className="size-3.5 text-muted-foreground" />
                Duplicar nó
              </button>

              {/* Enable / Disable */}
              <button
                type="button"
                onClick={handleToggleEnabled}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs font-medium text-foreground transition-colors hover:bg-muted"
              >
                <Power className="size-3.5 text-muted-foreground" />
                {enabled ? "Desativar nó" : "Ativar nó"}
              </button>

              <div className="my-1 h-px bg-border" />

              {/* Delete */}
              <button
                type="button"
                onClick={handleDelete}
                className="flex w-full items-center gap-2.5 px-3 py-2 text-left text-xs font-medium text-destructive transition-colors hover:bg-red-50 dark:hover:bg-red-950/30"
              >
                <Trash2 className="size-3.5" />
                Excluir nó
              </button>
            </div>
          )}
        </div>
      </div>

      {/* ── Config summary rows ── */}
      {summaryRows.length > 0 && (
        <div className="mx-3 mb-2 rounded-lg border border-border/50 bg-muted/30 px-2.5 py-2">
          <div className="grid grid-cols-[68px_1fr] items-center gap-y-1.5">
            {summaryRows.map((row) => (
              <Fragment key={row.label}>
                <span className="text-[10px] font-medium text-muted-foreground">{row.label}</span>
                <div className="flex justify-end">
                  {row.badge ? (
                    <span className="inline-flex items-center rounded border border-border/60 bg-background px-1.5 py-0.5 font-mono text-[10px] font-semibold text-foreground">
                      {row.value}
                    </span>
                  ) : (
                    <span className="max-w-[130px] truncate text-right text-[10px] text-foreground">
                      {row.value}
                    </span>
                  )}
                </div>
              </Fragment>
            ))}
          </div>
        </div>
      )}

      {/* ── Code / SQL dark block ── */}
      {codeContent && (
        <div className="mx-3 mb-3 overflow-hidden rounded-lg bg-[#1a1b26] px-2.5 py-2">
          <p className="font-mono text-[10px] leading-relaxed text-[#a5b4fc] break-all line-clamp-3">
            {codeContent}
          </p>
        </div>
      )}

      {/* ── Source handle(s) (right) ── */}
      {(() => {
        const isOutput = definition?.category === "output" && definition?.type !== "truncate_table"
        if (isOutput) return null

        // IF node: two handles (true / false)
        if (definition?.type === "if_node") {
          return (
            <>
              <Handle
                type="source"
                position={Position.Right}
                id="true"
                style={{ top: "35%" }}
                className={cn(
                  "!size-3 !-right-2 !rounded-full !border-2 !border-background !transition-transform hover:!scale-125",
                  "!bg-emerald-500",
                )}
              />
              <span
                className="pointer-events-none absolute text-[9px] font-bold text-emerald-500"
                style={{ right: 10, top: "35%", transform: "translateY(-50%)" }}
              >
                V
              </span>
              <Handle
                type="source"
                position={Position.Right}
                id="false"
                style={{ top: "65%" }}
                className={cn(
                  "!size-3 !-right-2 !rounded-full !border-2 !border-background !transition-transform hover:!scale-125",
                  "!bg-red-500",
                )}
              />
              <span
                className="pointer-events-none absolute text-[9px] font-bold text-red-500"
                style={{ right: 10, top: "65%", transform: "translateY(-50%)" }}
              >
                F
              </span>
            </>
          )
        }

        // Switch node: dynamic handles from cases + default
        if (definition?.type === "switch_node") {
          const cases: { label: string }[] = Array.isArray(nodeData.cases) ? (nodeData.cases as { label: string }[]) : []
          const handleIds = [...cases.map((c) => c.label).filter(Boolean), "default"]
          const count = handleIds.length || 1
          return (
            <>
              {handleIds.map((hId, idx) => {
                const pct = count === 1 ? 50 : 20 + (idx * 60) / (count - 1)
                return (
                  <Fragment key={hId}>
                    <Handle
                      type="source"
                      position={Position.Right}
                      id={hId}
                      style={{ top: `${pct}%` }}
                      className={cn(
                        "!size-3 !-right-2 !rounded-full !border-2 !border-background !transition-transform hover:!scale-125",
                        hId === "default" ? "!bg-gray-400" : theme.handleColor,
                      )}
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

        // Default: single handle
        return (
          <Handle
            type="source"
            position={Position.Right}
            className={cn(
              "!size-3.5 !-right-2 !rounded-full !border-2 !border-background !transition-transform hover:!scale-125",
              theme.handleColor,
            )}
          />
        )
      })()}
    </div>
  )
}

export const WorkflowNode = memo(WorkflowNodeComponent)
