"use client"

import { Fragment, memo, useCallback, useEffect, useMemo, useRef, useState } from "react"
import { Handle, Position, useReactFlow, type NodeProps } from "@xyflow/react"
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  Copy,
  Info,
  Loader2,
  MoreHorizontal,
  Pencil,
  Play,
  Power,
  PowerOff,
  RefreshCw,
  Trash2,
  XCircle,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { getNodeDefinition, type NodeDefinition } from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import { useNodeExecution } from "@/lib/workflow/execution-context"
import { useNodeActions } from "@/lib/workflow/node-actions-context"

const VAR_REF_RE = /\{\{\s*vars\.[A-Za-z_][A-Za-z0-9_]*\s*\}\}/g

function countVarRefs(data: Record<string, unknown>): number {
  const text = JSON.stringify(data)
  return (text.match(VAR_REF_RE) ?? []).length
}

// ─── Tone mapping (from registry `color` → handoff tone) ───────────────────────

type Tone = "purple" | "emerald" | "orange" | "cyan" | "slate" | "pink"

const COLOR_TO_TONE: Record<string, Tone> = {
  amber: "purple",     // triggers
  blue: "emerald",     // inputs (actions)
  violet: "cyan",      // transforms
  emerald: "emerald",  // outputs (actions)
  orange: "orange",    // decision / logic
  pink: "pink",        // ai
  slate: "slate",      // storage / utility
  red: "orange",       // dead letter → logic
  indigo: "cyan",      // call workflow → transform
}

function pickTone(def: NodeDefinition | undefined, customColor: string | null): Tone {
  if (!def && !customColor) return "slate"
  if (customColor) return "slate" // custom color goes via inline style; default tone class for chrome
  return COLOR_TO_TONE[def?.color ?? ""] ?? "slate"
}

// ─── Config summary helper (keeps the same logic as before) ────────────────────

interface SummaryRow {
  label: string
  value: string
  badge?: boolean
}

function getNodeSummaryRows(type: string, data: Record<string, unknown>): SummaryRow[] {
  const s = (v: unknown) => (v != null && String(v).trim() ? String(v).trim() : null)

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

// ─── Status meta ───────────────────────────────────────────────────────────────

interface StatusMeta {
  label: string
  dot: string
  text: string
  pulse?: boolean
  cls?: "is-running" | "is-success" | "is-error" | "is-handled-error"
}

function computeStatus(
  execStatus: string | undefined,
  enabled: boolean,
): StatusMeta {
  if (execStatus === "running") {
    return { label: "executando", dot: "#0ea5e9", text: "text-sky-600", pulse: true, cls: "is-running" }
  }
  if (execStatus === "success") {
    return { label: "ok", dot: "#10b981", text: "text-emerald-600", cls: "is-success" }
  }
  if (execStatus === "handled_error") {
    return { label: "tratado", dot: "#fb7185", text: "text-rose-500", cls: "is-handled-error" }
  }
  if (execStatus === "error") {
    return { label: "erro", dot: "#f43f5e", text: "text-rose-600", cls: "is-error" }
  }
  if (!enabled) {
    return { label: "desativado", dot: "#cbd5e1", text: "text-slate-500" }
  }
  return { label: "idle", dot: "#cbd5e1", text: "text-slate-500" }
}

// ─── Handle helpers ────────────────────────────────────────────────────────────

const HANDLE_CLS = "wf-handle"

function portTopPct(i: number, total: number): string {
  return `${((i + 1) * 100) / (total + 1)}%`
}

// ─── Node component ────────────────────────────────────────────────────────────

function WorkflowNodeComponent({ id, data, selected, type }: NodeProps) {
  const { deleteElements, setNodes, getNode } = useReactFlow()
  const { onExecuteNode } = useNodeActions()

  const definition  = getNodeDefinition(type ?? "")
  const nodeData    = data as Record<string, unknown>
  const isPending   = nodeData.__pending === true
  const customIcon  = typeof nodeData.icon === "string" ? nodeData.icon : null
  const customColor = typeof nodeData.color === "string" && nodeData.color.trim() !== "" ? nodeData.color : null
  const Icon        = getNodeIcon(customIcon ?? definition?.icon ?? "Database")
  const label       = (nodeData.label as string | undefined) ?? definition?.label ?? type ?? ""
  const enabled     = nodeData.enabled !== false
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
  const tone        = pickTone(definition, customColor)

  const codeContent = useMemo(() => {
    if (type === "sql_database" || type === "polling") {
      const q = (nodeData.query as string | undefined)?.trim()
      return q || null
    }
    if (type === "code") {
      const c = (nodeData.code as string | undefined)?.trim()
      return c || null
    }
    if (type === "sql_script") {
      const c = (nodeData.script as string | undefined)?.trim()
      return c || null
    }
    return null
  }, [type, nodeData])

  const statusMeta = computeStatus(execState?.status, enabled)

  // ── Inline title editing ─────────────────────────────────────────────────
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(label)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => { setDraft(label) }, [label])
  useEffect(() => { if (editing) inputRef.current?.select() }, [editing])

  const commitTitle = useCallback(() => {
    const v = (draft || "").trim() || label
    setNodes((nds) =>
      nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, label: v } } : n)),
    )
    setEditing(false)
  }, [draft, id, label, setNodes])

  const cancelEdit = useCallback(() => {
    setDraft(label)
    setEditing(false)
  }, [label])

  // ── Menu ─────────────────────────────────────────────────────────────────
  const [menuOpen, setMenuOpen] = useState(false)
  const [infoOpen, setInfoOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const btnRef = useRef<HTMLButtonElement>(null)
  const infoRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!menuOpen) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (menuRef.current?.contains(t)) return
      if (btnRef.current?.contains(t)) return
      setMenuOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setMenuOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [menuOpen])

  useEffect(() => {
    if (!infoOpen) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (infoRef.current?.contains(t)) return
      setInfoOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setInfoOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [infoOpen])

  // ── Actions ──────────────────────────────────────────────────────────────
  const handleToggleEnabled = useCallback(() => {
    setNodes((nds) =>
      nds.map((n) => (n.id === id ? { ...n, data: { ...n.data, enabled: !enabled } } : n)),
    )
    setMenuOpen(false)
  }, [id, enabled, setNodes])

  const handleExecute = useCallback(() => {
    onExecuteNode(id)
    setMenuOpen(false)
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
    setMenuOpen(false)
  }, [id, getNode, setNodes])

  // ── Handles layout ───────────────────────────────────────────────────────
  const isTrigger = definition?.category === "trigger"

  type PortDef = { id: string; label?: string; colorClass?: string }
  const outputs: PortDef[] = useMemo(() => {
    if (type === "if_node") {
      return [
        { id: "true", label: "V", colorClass: "wf-handle--true" },
        { id: "false", label: "F", colorClass: "wf-handle--false" },
      ]
    }
    if (type === "switch_node") {
      const cases: { label: string }[] = Array.isArray(nodeData.cases)
        ? (nodeData.cases as { label: string }[])
        : []
      const ids = [...cases.map((c) => c.label).filter(Boolean), "default"]
      return ids.map((cid) => ({ id: cid, label: cid.length > 8 ? cid.slice(0, 8) + "…" : cid }))
    }
    const out: PortDef[] = [{ id: "success" }]
    if (definition?.errorHandle) {
      out.push({ id: "on_error", label: "err", colorClass: "wf-handle--error" })
    }
    return out
  }, [type, nodeData.cases, definition?.errorHandle])

  // ── Render ───────────────────────────────────────────────────────────────
  return (
    <div
      className={cn(
        "wf-node group/node relative",
        selected && "is-selected",
        !enabled && "is-disabled",
        isPending && "is-pending",
        !isPending && statusMeta.cls,
      )}
      data-tone={tone}
      style={{ width: 260 }}
    >
      <div className="wf-node__aura" />
      <div className="wf-node__corner" />

      {/* Ghost badge (IA) */}
      {isPending && (
        <span className="absolute -top-2 -right-2 z-20 flex items-center gap-0.5 rounded-full bg-violet-500 px-1.5 py-0.5 text-[9px] font-bold text-white shadow-sm">
          <Bot className="size-2.5" />
          IA
        </span>
      )}

      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="relative z-10 flex items-center gap-2.5 px-3.5 pt-3 pb-2.5">
        <div
          className="wf-node__icon-tile"
          style={customColor ? { background: `${customColor}22`, color: customColor, boxShadow: `0 0 0 1px ${customColor}40, 0 1px 2px rgba(15,23,42,.04)` } : undefined}
        >
          <Icon className="size-[15px]" strokeWidth={2} />
        </div>

        <div className="min-w-0 flex-1">
          {editing ? (
            <input
              ref={inputRef}
              className="nodrag w-full rounded-md border border-slate-300 bg-white/95 px-1.5 py-0.5 text-[13px] font-semibold tracking-[-0.01em] text-slate-900 outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 dark:border-slate-600 dark:bg-slate-800/80 dark:text-slate-100"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitTitle}
              onKeyDown={(e) => {
                if (e.key === "Enter") commitTitle()
                if (e.key === "Escape") cancelEdit()
              }}
              onMouseDown={(e) => e.stopPropagation()}
            />
          ) : (
            <div
              className="wf-node__title-editable line-clamp-2 break-words text-[13px] font-semibold leading-tight tracking-[-0.01em] text-slate-800 dark:text-slate-100"
              onDoubleClick={(e) => {
                e.stopPropagation()
                setEditing(true)
              }}
              title="Clique-duplo para renomear"
            >
              {label}
            </div>
          )}
          {definition?.description && !editing && (
            <div className="mt-0.5 truncate font-mono text-[10.5px] leading-tight text-slate-500 dark:text-slate-400">
              {definition.description}
            </div>
          )}
        </div>

        <div className="flex items-center gap-1">
          <span
            className="wf-node__status-chip"
            title={`Status: ${statusMeta.label}`}
          >
            <span
              className={cn("wf-node__status-dot", statusMeta.pulse && "is-pulsing")}
              style={{ background: statusMeta.dot }}
            />
          </span>
          <button
            ref={btnRef}
            type="button"
            onMouseDown={(e) => e.stopPropagation()}
            onClick={(e) => {
              e.stopPropagation()
              setMenuOpen((o) => !o)
            }}
            className={cn(
              "nodrag flex size-[22px] items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-900/5 hover:text-slate-700 dark:hover:bg-white/10 dark:hover:text-slate-200",
              menuOpen && "bg-slate-900/10 text-slate-800 dark:bg-white/10 dark:text-slate-100",
            )}
            aria-label="Ações do nó"
          >
            <MoreHorizontal className="size-3.5" />
          </button>
        </div>
      </div>

      {/* ── Menu popover ───────────────────────────────────────────────── */}
      {menuOpen && (
        <div
          ref={menuRef}
          className="nodrag absolute right-2 top-10 z-50 w-[180px] rounded-xl border border-slate-200 bg-white/97 p-1 shadow-[0_20px_40px_-12px_rgba(15,23,42,.2)] backdrop-blur-md dark:border-slate-700 dark:bg-slate-900/95"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          <button
            onClick={() => {
              setEditing(true)
              setMenuOpen(false)
            }}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-slate-700 transition-colors hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <Pencil className="size-3.5" />
            Renomear
          </button>
          <button
            onClick={handleExecute}
            disabled={!enabled}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-slate-700 transition-colors hover:bg-slate-100 disabled:opacity-40 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <Play className="size-3.5" />
            Executar
          </button>
          <button
            onClick={handleToggleEnabled}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-slate-700 transition-colors hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            {enabled ? <PowerOff className="size-3.5" /> : <Power className="size-3.5" />}
            {enabled ? "Desativar" : "Ativar"}
          </button>
          <button
            onClick={handleDuplicate}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-slate-700 transition-colors hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <Copy className="size-3.5" />
            Duplicar
          </button>
          <div className="my-1 h-px bg-slate-200 dark:bg-slate-700" />
          <button
            onClick={() => {
              setMenuOpen(false)
              setInfoOpen(true)
            }}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-slate-700 transition-colors hover:bg-slate-100 dark:text-slate-200 dark:hover:bg-slate-800"
          >
            <Info className="size-3.5" />
            Info
          </button>
          <div className="my-1 h-px bg-slate-200 dark:bg-slate-700" />
          <button
            onClick={handleDelete}
            className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-[12px] text-rose-600 transition-colors hover:bg-rose-50 dark:hover:bg-rose-950/40"
          >
            <Trash2 className="size-3.5" />
            Remover
          </button>
        </div>
      )}

      {/* ── Info popover ──────────────────────────────────────────────── */}
      {infoOpen && (
        <div
          ref={infoRef}
          className="nodrag absolute right-2 top-10 z-50 w-[220px] rounded-xl border border-slate-200 bg-white/97 p-2.5 shadow-[0_20px_40px_-12px_rgba(15,23,42,.2)] backdrop-blur-md dark:border-slate-700 dark:bg-slate-900/95"
          onMouseDown={(e) => e.stopPropagation()}
          onClick={(e) => e.stopPropagation()}
        >
          <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
            <Info className="size-3" />
            Status de execução
          </div>
          <ul className="space-y-1.5 text-[11.5px] text-slate-700 dark:text-slate-200">
            <li className="flex items-center gap-2">
              <span className="inline-block size-2 rounded-full bg-slate-300" />
              <span className="font-semibold">idle</span>
              <span className="text-slate-500 dark:text-slate-400">— ainda não executou</span>
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block size-2 rounded-full bg-sky-500" />
              <span className="font-semibold">executando</span>
              <span className="text-slate-500 dark:text-slate-400">— em andamento</span>
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block size-2 rounded-full bg-emerald-500" />
              <span className="font-semibold">ok</span>
              <span className="text-slate-500 dark:text-slate-400">— sucesso</span>
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block size-2 rounded-full bg-rose-400" />
              <span className="font-semibold">tratado</span>
              <span className="text-slate-500 dark:text-slate-400">— erro capturado</span>
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block size-2 rounded-full bg-rose-600" />
              <span className="font-semibold">erro</span>
              <span className="text-slate-500 dark:text-slate-400">— falhou</span>
            </li>
            <li className="flex items-center gap-2">
              <span className="inline-block size-2 rounded-full bg-slate-300" />
              <span className="font-semibold">desativado</span>
              <span className="text-slate-500 dark:text-slate-400">— nó pausado</span>
            </li>
          </ul>
        </div>
      )}

      {/* ── Divider ────────────────────────────────────────────────────── */}
      <div className="wf-node__divider" />

      {/* ── Body (glanceable) ──────────────────────────────────────────── */}
      <div className="nodrag relative z-10 mx-3 mb-4 mt-2">
        <div className="wf-node__body space-y-2">
          {/* Exec metrics / disabled / badges row */}
          {(execState?.status || retryActive || varRefCount > 0) && (
            <div className="flex flex-wrap items-center gap-1.5 text-[10px]">
              {execState?.status === "running" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-sky-500/10 px-1.5 py-0.5 font-semibold text-sky-600 dark:text-sky-400">
                  <Loader2 className="size-2.5 animate-spin" />
                  executando
                </span>
              )}
              {execState?.status === "success" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-1.5 py-0.5 font-semibold text-emerald-600 dark:text-emerald-400">
                  <CheckCircle2 className="size-2.5" />
                  {typeof execState.output?.row_count === "number"
                    ? `${execState.output.row_count} linhas`
                    : "ok"}
                  {typeof execState.duration_ms === "number" && (
                    <span className="opacity-60">· {execState.duration_ms}ms</span>
                  )}
                </span>
              )}
              {execState?.status === "handled_error" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-rose-400/10 px-1.5 py-0.5 font-semibold text-rose-500">
                  <AlertTriangle className="size-2.5" />
                  tratado
                </span>
              )}
              {execState?.status === "error" && (
                <span className="inline-flex items-center gap-1 rounded-full bg-rose-500/10 px-1.5 py-0.5 font-semibold text-rose-600">
                  <XCircle className="size-2.5" />
                  erro
                </span>
              )}
              {retryActive && (
                <span
                  className="inline-flex items-center gap-0.5 rounded-full bg-sky-500/10 px-1.5 py-0.5 font-semibold text-sky-600 dark:text-sky-400"
                  title={`Retry: ${retryPolicy?.max_attempts} tentativas (${retryPolicy?.backoff_strategy ?? "none"})`}
                >
                  <RefreshCw className="size-2.5" />
                  {retryPolicy?.max_attempts}x
                </span>
              )}
              {varRefCount > 0 && (
                <span
                  className="inline-flex items-center gap-0.5 rounded-full bg-violet-500/10 px-1.5 py-0.5 font-mono font-semibold text-violet-600 dark:text-violet-400"
                  title={`${varRefCount} referência${varRefCount > 1 ? "s" : ""} a variável`}
                >
                  {"{}"}
                  {varRefCount}
                </span>
              )}
            </div>
          )}

          {/* Summary rows */}
          {summaryRows.length > 0 && (
            <div className="grid grid-cols-[auto_1fr] items-center gap-x-2 gap-y-1">
              {summaryRows.map((row) => (
                <Fragment key={row.label}>
                  <span className="font-mono text-[10px] text-slate-400 dark:text-slate-500">
                    {row.label}
                  </span>
                  <div className="flex min-w-0 justify-end">
                    {row.badge ? (
                      <span className="inline-flex max-w-full items-center truncate rounded border border-slate-200 bg-white px-1.5 py-0.5 font-mono text-[10.5px] font-semibold text-slate-700 dark:border-slate-700 dark:bg-slate-800/60 dark:text-slate-200">
                        {row.value}
                      </span>
                    ) : (
                      <span className="max-w-full truncate text-right font-mono text-[10.5px] text-slate-700 dark:text-slate-300">
                        {row.value}
                      </span>
                    )}
                  </div>
                </Fragment>
              ))}
            </div>
          )}

          {/* Code / SQL block */}
          {codeContent && (
            <div className="wf-node__code">
              <pre className="line-clamp-4">{codeContent}</pre>
            </div>
          )}

          {/* Empty state — keep body present but subtle when nothing to show */}
          {summaryRows.length === 0 && !codeContent && !execState?.status && !retryActive && varRefCount === 0 && (
            <div className="flex items-center gap-1.5 font-mono text-[10.5px] text-slate-400 dark:text-slate-500">
              <span className="inline-block size-1 rounded-full bg-slate-300 dark:bg-slate-600" />
              {definition?.category === "trigger" ? "aguardando disparo" : "sem configuração"}
            </div>
          )}
        </div>
      </div>

      {/* ── Handles ────────────────────────────────────────────────────── */}
      {!isTrigger && (
        <Handle
          type="target"
          position={Position.Left}
          id="in"
          className={HANDLE_CLS}
          style={{ top: "50%" }}
        />
      )}

      {outputs.map((p, i) => {
        const top = portTopPct(i, outputs.length)
        return (
          <Fragment key={`out-${p.id}`}>
            <Handle
              type="source"
              position={Position.Right}
              id={p.id}
              className={cn(HANDLE_CLS, p.colorClass)}
              style={{ top }}
            />
            {p.label && (
              <span
                className="wf-node__handle-label"
                style={{ top, right: 14 }}
              >
                {p.label}
              </span>
            )}
          </Fragment>
        )
      })}
    </div>
  )
}

export const WorkflowNode = memo(WorkflowNodeComponent)
