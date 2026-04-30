"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import {
  Hand,
  LayoutGrid,
  List,
  MousePointer2,
  Plus,
  RotateCcw,
  Search,
  SearchX,
  X,
} from "lucide-react"
import {
  NODE_REGISTRY,
  type NodeDefinition,
} from "@/lib/workflow/types"
import { getNodeIcon } from "@/lib/workflow/node-icons"
import { useCustomNodes } from "@/lib/workflow/custom-nodes-context"
import type { CustomNodeDefinition } from "@/lib/auth"

interface NodeLibraryProps {
  open: boolean
  onClose: () => void
}

type Tone = "purple" | "emerald" | "orange" | "cyan" | "slate" | "pink" | "neutral"

interface ToneDef {
  name: string
}

const TONES: Record<Tone, ToneDef> = {
  purple: { name: "Gatilhos" },
  emerald: { name: "Entradas" },
  orange: { name: "Lógica" },
  cyan: { name: "Transformação" },
  slate: { name: "Armazenamento" },
  pink: { name: "IA" },
  neutral: { name: "Outros" },
}

const TONE_ORDER: Tone[] = [
  "purple",
  "emerald",
  "cyan",
  "orange",
  "slate",
  "pink",
  "neutral",
]

const COLOR_TO_TONE: Record<string, Tone> = {
  amber: "purple",
  blue: "emerald",
  violet: "cyan",
  emerald: "emerald",
  orange: "orange",
  pink: "pink",
  slate: "slate",
  red: "orange",
  indigo: "cyan",
  // ``stone`` agrupa nós que ainda não pertencem a uma categoria
  // específica de UX (SQL Database, API REST, Dados Inline...) — caem
  // no grupo "Outros" da biblioteca até ganharem casa própria.
  stone: "neutral",
}

function toneOf(color: string): Tone {
  return COLOR_TO_TONE[color] ?? "slate"
}

// ─── Mini-preview bodies per node type ──────────────────────────────
function MiniBody({ node }: { node: NodeDefinition }) {
  const d = (node.defaultData ?? {}) as Record<string, unknown>

  const chip = (bg: string, color: string, label: string) => (
    <span
      className="mono rounded px-1 py-[1px] text-[8.5px] font-semibold"
      style={{ background: bg, color }}
    >
      {label}
    </span>
  )

  switch (node.type) {
    case "cron":
      return <span className="mono truncate text-[10px]">{String(d.cron_expression ?? "*/5 * * * *")}</span>
    case "webhook":
      return (
        <div className="flex items-center gap-1.5">
          {chip("rgb(220 252 231)", "rgb(22 101 52)", "POST")}
          <span className="mono truncate text-[10px] opacity-80">/webhook</span>
        </div>
      )
    case "manual":
      return <span className="truncate text-[10px] italic">Execução manual</span>
    case "workflow_input":
      return <span className="truncate text-[10px]">Entrada de sub-fluxo</span>
    case "sql_database":
      return (
        <div className="mono rounded bg-slate-900 px-1.5 py-1 text-[9px] leading-tight">
          <span className="text-pink-400">SELECT</span> <span className="text-slate-300">*</span>
        </div>
      )
    case "sql_script":
      return (
        <div className="mono rounded bg-slate-900 px-1.5 py-1 text-[9px] leading-tight">
          <span className="text-purple-400">EXEC</span> <span className="text-slate-300">script</span>
        </div>
      )
    case "csv_input":
      return <div className="flex items-center gap-1">{chip("rgb(219 234 254)", "rgb(30 64 175)", "CSV")}<span className="truncate text-[10px]">arquivo.csv</span></div>
    case "excel_input":
      return <div className="flex items-center gap-1">{chip("rgb(220 252 231)", "rgb(22 101 52)", "XLSX")}<span className="truncate text-[10px]">planilha</span></div>
    case "http_request":
      return (
        <div className="flex items-center gap-1.5">
          {chip("rgb(219 234 254)", "rgb(30 64 175)", String(d.method ?? "GET"))}
          <span className="mono truncate text-[10px] opacity-80">api/…</span>
        </div>
      )
    case "inline_data":
      return <span className="mono truncate text-[10px]">[ {'{}'} , ... ]</span>
    case "mapper":
      return <span className="mono truncate text-[10px]">a → b</span>
    case "filter":
      return <span className="mono truncate text-[10px]">where {"{…}"}</span>
    case "aggregator":
      return <span className="mono truncate text-[10px]">group by</span>
    case "deduplication":
      return <span className="mono truncate text-[10px]">distinct keys</span>
    case "math":
      return <span className="mono truncate text-[10px]">x = a + b</span>
    case "code":
      return (
        <div className="mono rounded bg-slate-900 px-1.5 py-1 text-[9px] leading-tight">
          <span className="text-purple-400">def</span> <span className="text-cyan-300">run</span>
        </div>
      )
    case "loop":
      return <span className="mono truncate text-[10px]">∀ items</span>
    case "sync":
      return <span className="truncate text-[10px]">aguarda ramos</span>
    case "if_node":
      return <span className="mono truncate text-[10px]">if · true / false</span>
    case "switch_node":
      return (
        <div className="flex gap-0.5">
          {["A", "B", "C"].map((r) => (
            <span key={r} className="mono rounded bg-orange-100 px-1 text-[8px] text-orange-700">
              {r}
            </span>
          ))}
        </div>
      )
    case "composite_insert":
      return <span className="truncate text-[10px]">Nó composto</span>
    case "truncate_table":
      return <span className="mono truncate text-[10px]">TRUNCATE</span>
    case "bulk_insert":
      return <span className="mono truncate text-[10px]">INSERT INTO</span>
    case "loadNode":
      return <span className="mono truncate text-[10px]">→ tabela</span>
    case "dead_letter":
      return <span className="truncate text-[10px]">linhas com erro</span>
    case "workflow_output":
      return <span className="truncate text-[10px]">Saída de sub-workflow</span>
    case "call_workflow":
      return <span className="mono truncate text-[10px]">exec workflow</span>
    case "aiNode":
      return (
        <div className="flex items-center gap-1.5">
          {chip("rgb(252 231 243)", "rgb(157 23 77)", "LLM")}
          <span className="truncate text-[10px] italic opacity-80">prompt…</span>
        </div>
      )
    default:
      return <span className="truncate text-[10px] opacity-60">—</span>
  }
}

// ─── Unified library item (node registry + custom) ─────────────────
type LibItem =
  | { kind: "node"; def: NodeDefinition; tone: Tone }
  | { kind: "custom"; custom: CustomNodeDefinition; tone: Tone }

function itemKey(item: LibItem): string {
  return item.kind === "node" ? `n:${item.def.type}` : `c:${item.custom.id}`
}

function itemLabel(item: LibItem): string {
  return item.kind === "node" ? item.def.label : item.custom.name
}

function itemDesc(item: LibItem): string {
  if (item.kind === "node") return item.def.description
  return (
    item.custom.description ??
    `${item.custom.blueprint?.tables?.length ?? 0} tabela(s) · v${item.custom.version}`
  )
}

function itemTypeId(item: LibItem): string {
  return item.kind === "node" ? item.def.type : "composite_insert"
}

function itemIcon(item: LibItem): string {
  if (item.kind === "node") return item.def.icon
  return item.custom.icon ?? "Boxes"
}

function onDragStartForItem(event: React.DragEvent, item: LibItem) {
  event.dataTransfer.effectAllowed = "move"
  if (item.kind === "node") {
    event.dataTransfer.setData("application/reactflow-type", item.def.type)
  } else {
    event.dataTransfer.setData("application/reactflow-type", "composite_insert")
    event.dataTransfer.setData("application/reactflow-definition-id", item.custom.id)
  }
}

// ─── Card (grid view) ─────────────────────────────────────────────
function LibCard({ item }: { item: LibItem }) {
  const Icon = getNodeIcon(itemIcon(item))
  return (
    <div
      draggable
      onDragStart={(e) => onDragStartForItem(e, item)}
      className={`lib-card lib-tone`}
      data-tone={item.tone}
      title={`${itemLabel(item)} — arraste para o canvas`}
    >
      <div className="lib-card-accent" />
      <div className="lib-card-header">
        <div className="lib-icon-tile">
          <Icon className="size-3.5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="lib-card-title">{itemLabel(item)}</div>
          <div className="lib-card-subtitle">{itemTypeId(item)}</div>
        </div>
      </div>
      <div className="lib-card-body">
        {item.kind === "node" ? (
          <MiniBody node={item.def} />
        ) : (
          <span className="truncate text-[10px]">{itemDesc(item)}</span>
        )}
      </div>
    </div>
  )
}

// ─── Row (list view) ──────────────────────────────────────────────
function LibRow({ item }: { item: LibItem }) {
  const Icon = getNodeIcon(itemIcon(item))
  return (
    <div
      draggable
      onDragStart={(e) => onDragStartForItem(e, item)}
      className="lib-list-row lib-tone"
      data-tone={item.tone}
      title={itemDesc(item)}
    >
      <div className="lib-icon-tile lib-icon-tile--sm">
        <Icon className="size-3" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="lib-list-title">{itemLabel(item)}</div>
        <div className="lib-list-sub">{itemDesc(item)}</div>
      </div>
    </div>
  )
}

// ─── Main drawer ──────────────────────────────────────────────────
export function NodeLibrary({ open, onClose }: NodeLibraryProps) {
  const [query, setQuery] = useState("")
  const [layout, setLayout] = useState<"grid" | "list">("grid")
  const [activeTones, setActiveTones] = useState<Set<Tone>>(
    () => new Set(TONE_ORDER),
  )
  const inputRef = useRef<HTMLInputElement>(null)
  const drawerRef = useRef<HTMLDivElement>(null)

  const customNodes = useCustomNodes()

  // Focus search on open
  useEffect(() => {
    if (!open) return
    const t = setTimeout(() => inputRef.current?.focus(), 50)
    return () => clearTimeout(t)
  }, [open])

  // ESC closes (only while open)
  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose()
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open, onClose])

  // Click-outside fecha o drawer. Atrasamos o registro do listener em 1 tick
  // pra nao capturar o proprio click que abriu a biblioteca (esse click
  // viaja como bubble depois do setOpen, e a gente nao quer que ele dispare
  // close imediato). Usa mousedown na fase de capture pra detectar antes de
  // qualquer handler downstream.
  useEffect(() => {
    if (!open) return
    const onMouseDown = (e: MouseEvent) => {
      const target = e.target as Node | null
      if (!target) return
      if (drawerRef.current && !drawerRef.current.contains(target)) {
        onClose()
      }
    }
    const timer = setTimeout(() => {
      document.addEventListener("mousedown", onMouseDown, true)
    }, 0)
    return () => {
      clearTimeout(timer)
      document.removeEventListener("mousedown", onMouseDown, true)
    }
  }, [open, onClose])

  const items: LibItem[] = useMemo(() => {
    const baseNodes: LibItem[] = NODE_REGISTRY.filter(
      (n) => n.type !== "composite_insert",
    ).map((def) => ({ kind: "node" as const, def, tone: toneOf(def.color) }))

    const custom: LibItem[] = customNodes.map((c) => ({
      kind: "custom" as const,
      custom: c,
      tone: "emerald" as Tone,
    }))

    return [...baseNodes, ...custom]
  }, [customNodes])

  const filtered = useMemo(() => {
    const q = query.toLowerCase().trim()
    return items.filter((item) => {
      if (!activeTones.has(item.tone)) return false
      if (!q) return true
      const hay = [itemLabel(item), itemTypeId(item), itemDesc(item)]
        .join(" ")
        .toLowerCase()
      return hay.includes(q)
    })
  }, [items, query, activeTones])

  const grouped = useMemo(() => {
    const out: Record<Tone, LibItem[]> = {
      purple: [],
      emerald: [],
      orange: [],
      cyan: [],
      slate: [],
      pink: [],
      neutral: [],
    }
    filtered.forEach((it) => out[it.tone].push(it))
    return out
  }, [filtered])

  const toneCount = useMemo(() => {
    const out: Record<Tone, number> = {
      purple: 0,
      emerald: 0,
      orange: 0,
      cyan: 0,
      slate: 0,
      pink: 0,
      neutral: 0,
    }
    items.forEach((it) => (out[it.tone] += 1))
    return out
  }, [items])

  const totalCount = items.length
  const shownCount = filtered.length

  const toggleTone = (t: Tone) => {
    setActiveTones((prev) => {
      const next = new Set(prev)
      // If all tones are active, start fresh with just the clicked one
      if (next.size === TONE_ORDER.length) {
        return new Set([t])
      }
      if (next.has(t)) next.delete(t)
      else next.add(t)
      if (next.size === 0) return new Set(TONE_ORDER)
      return next
    })
  }
  const resetTones = () => setActiveTones(new Set(TONE_ORDER))

  return (
    <div
      ref={drawerRef}
      className={`lib-drawer${open ? " lib-drawer--open" : ""}`}
      aria-hidden={!open}
    >
      {/* Header */}
      <div className="lib-header">
        <div className="lib-header-badge">
          <LayoutGrid className="size-3.5" />
        </div>
        <div className="min-w-0">
          <div className="lib-header-title">Biblioteca de Nós</div>
          <div className="lib-header-sub">
            {shownCount} de {totalCount}
          </div>
        </div>
        <div className="flex-1" />
        <div className="lib-layout-toggle">
          <button
            type="button"
            onClick={() => setLayout("grid")}
            className={layout === "grid" ? "active" : ""}
            title="Visualizar em grade"
          >
            <LayoutGrid className="size-3" />
          </button>
          <button
            type="button"
            onClick={() => setLayout("list")}
            className={layout === "list" ? "active" : ""}
            title="Visualizar em lista"
          >
            <List className="size-3" />
          </button>
        </div>
        <button type="button" onClick={onClose} className="lib-close" title="Fechar">
          <X className="size-3.5" />
        </button>
      </div>

      {/* Search */}
      <div className="lib-search">
        <Search className="size-3.5 shrink-0 text-muted-foreground" />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Buscar por nome, tipo, descrição…"
        />
        {query && (
          <button
            type="button"
            onClick={() => setQuery("")}
            className="text-muted-foreground hover:text-foreground"
            aria-label="Limpar busca"
          >
            <X className="size-3" />
          </button>
        )}
      </div>

      {/* Group filter chips foram removidos pra economizar espaço vertical —
          a busca por texto cobre o caso comum, e os grupos seguem visíveis
          como cabeçalhos de seção logo abaixo. Se precisar voltar como
          filtro, ver historico (campo activeTones / toneCount). */}

      {/* Body */}
      <div className="lib-body">
        {shownCount === 0 && (
          <div className="lib-empty">
            <div className="lib-empty-icon">
              <SearchX className="size-4" />
            </div>
            <div className="lib-empty-title">Nenhum nó encontrado</div>
            <div className="lib-empty-sub">Tente outra busca ou reative grupos</div>
          </div>
        )}

        {TONE_ORDER.map((tone) => {
          const list = grouped[tone]
          if (!list || list.length === 0) return null
          return (
            <div key={tone} className="lib-group-block lib-tone" data-tone={tone}>
              <div className="lib-group-header">
                <span
                  className="inline-block size-2 rounded-full"
                  style={{ background: `var(--tone-dot)` }}
                />
                <span className="lib-group-header-label">{TONES[tone].name}</span>
                <span className="lib-group-header-count">{list.length}</span>
                <div className="lib-group-header-divider" />
              </div>
              {layout === "grid" ? (
                <div className="lib-grid">
                  {list.map((item) => (
                    <LibCard key={itemKey(item)} item={item} />
                  ))}
                </div>
              ) : (
                <div className="lib-list">
                  {list.map((item) => (
                    <LibRow key={itemKey(item)} item={item} />
                  ))}
                </div>
              )}
            </div>
          )
        })}
      </div>

      {/* Footer */}
      <div className="lib-footer">
        <div className="flex items-center gap-1.5">
          <Hand className="size-3 opacity-70" />
          <span>Arraste pro canvas</span>
        </div>
        <span className="lib-footer-dot">·</span>
        <div className="flex items-center gap-1.5">
          <MousePointer2 className="size-3 opacity-70" />
          <span>Clique fora para fechar</span>
        </div>
        <div className="flex-1" />
        <kbd>Esc</kbd>
      </div>
    </div>
  )
}
