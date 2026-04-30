"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { createPortal } from "react-dom"
import { ChevronDown, Hash, Link2, Plus, Trash2, ArrowUp, ArrowDown } from "lucide-react"
import { cn } from "@/lib/utils"
import {
  useUpstreamFields,
  useUpstreamOutputs,
  type UpstreamSummary,
} from "@/lib/workflow/upstream-fields-context"
import { FieldChipPicker } from "@/components/workflow/nodes/field-chip-picker"
import { HelpTip } from "@/components/ui/help-tip"

interface OrderByItem {
  column: string
  direction: "asc" | "desc"
}

interface RecordIdConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

function normalizeOrderBy(raw: unknown): OrderByItem {
  const c = (raw ?? {}) as Record<string, unknown>
  return {
    column: (c.column as string) ?? "",
    direction: (c.direction as "asc" | "desc") ?? "asc",
  }
}

const FIELD_DRAG_TYPE = "application/x-shift-field"

// ── UpstreamLinkPicker ──────────────────────────────────────────────────────
//
// Picker estilo "compact chip" (mesmo padrao do Mapper) pra escolher um valor
// escalar de um no anterior. Salva como template ``{{upstream_results.<id>.data.0.<col>}}``,
// que o backend resolve via resolve_data → resolve_template.
// O usuario nunca digita o template — ve uma lista agrupada por no e clica.

const TEMPLATE_RE = /^\{\{\s*upstream_results\.([^.\s]+)\.data\.0\.([^.\s}]+)\s*\}\}$/

function extractScalarFields(output: Record<string, unknown> | null): string[] {
  if (!output) return []
  // Convencao da plataforma: nos publicam ``output.columns: string[]`` com a
  // lista de colunas, mesmo quando o dataset ta materializado em DuckDB
  // (sem rows inline). E o que o ``useUpstreamFields()`` consome. Tentamos
  // primeiro pra capturar a maioria dos nos.
  if (Array.isArray(output.columns)) {
    return (output.columns as unknown[]).filter(
      (c): c is string => typeof c === "string",
    )
  }
  // Fallback: vasculha o ``output_field`` (default ``data``) ou keys comuns
  // procurando por uma lista de objetos inline. Cobre nos que retornam o
  // resultado direto sem materializar (ex.: SQL com poucas linhas).
  const outputField = typeof output.output_field === "string" ? output.output_field : "data"
  const tryArray = (key: string): string[] | null => {
    const v = output[key]
    if (Array.isArray(v) && v.length > 0 && typeof v[0] === "object" && v[0] !== null) {
      return Object.keys(v[0] as Record<string, unknown>)
    }
    return null
  }
  return tryArray(outputField) ?? tryArray("data") ?? tryArray("rows") ?? []
}

const FIELD_REF_TYPE = "application/x-shift-field-ref"

// Helper compartilhado pelos dois estados (chip e botao vazio): le o payload
// do drag e converte em template ``{{upstream_results.<id>.data.0.<col>}}``.
// Prefere o ref enriquecido (``x-shift-field-ref``) que carrega o nodeId
// de origem; cai no campo bare + primeiro upstream como fallback.
function buildTemplateFromDrop(
  e: React.DragEvent,
  fallbackNodeId: string | null,
): string | null {
  const refRaw = e.dataTransfer.getData(FIELD_REF_TYPE)
  if (refRaw) {
    try {
      const ref = JSON.parse(refRaw) as { nodeId?: string; field?: string }
      if (ref.nodeId && ref.field) {
        return `{{upstream_results.${ref.nodeId}.data.0.${ref.field}}}`
      }
    } catch {
      // ignora payload mal-formado
    }
  }
  const field = e.dataTransfer.getData(FIELD_DRAG_TYPE)
  if (field && fallbackNodeId) {
    return `{{upstream_results.${fallbackNodeId}.data.0.${field}}}`
  }
  return null
}

function UpstreamLinkPicker({
  template,
  onChange,
}: {
  template: string
  onChange: (next: string) => void
}) {
  const upstreamOutputs = useUpstreamOutputs()
  const [open, setOpen] = useState(false)
  const triggerRef = useRef<HTMLButtonElement | null>(null)
  const popoverRef = useRef<HTMLDivElement | null>(null)
  const [pos, setPos] = useState<{ top: number; left: number; width: number } | null>(null)

  const sources = useMemo(() => {
    return upstreamOutputs
      .map((up) => ({ ...up, columns: extractScalarFields(up.output) }))
      .filter((s) => s.columns.length > 0)
  }, [upstreamOutputs])

  const parsed = useMemo(() => {
    const m = TEMPLATE_RE.exec(template)
    if (!m) return null
    const nodeId = m[1]
    const col = m[2]
    const up = upstreamOutputs.find((u) => u.nodeId === nodeId)
    return { nodeId, col, label: up?.label ?? nodeId, found: !!up }
  }, [template, upstreamOutputs])

  // Posiciona popover via portal (escapa overflow:hidden).
  useEffect(() => {
    if (!open) {
      setPos(null)
      return
    }
    const update = () => {
      const r = triggerRef.current?.getBoundingClientRect()
      if (!r) return
      const POPOVER_MIN = 240
      const width = Math.max(POPOVER_MIN, r.width)
      let left = r.left
      const maxLeft = window.innerWidth - width - 8
      if (left > maxLeft) left = maxLeft
      if (left < 8) left = 8
      setPos({ top: r.bottom + 4, left, width })
    }
    update()
    window.addEventListener("scroll", update, true)
    window.addEventListener("resize", update)
    return () => {
      window.removeEventListener("scroll", update, true)
      window.removeEventListener("resize", update)
    }
  }, [open])

  // Click-outside fecha
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (triggerRef.current?.contains(t)) return
      if (popoverRef.current?.contains(t)) return
      setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", onDown)
    document.addEventListener("keydown", onKey)
    return () => {
      document.removeEventListener("mousedown", onDown)
      document.removeEventListener("keydown", onKey)
    }
  }, [open])

  function pick(nodeId: string, col: string) {
    onChange(`{{upstream_results.${nodeId}.data.0.${col}}}`)
    setOpen(false)
  }

  // ── Drag-drop ───────────────────────────────────────────────────────────
  // Aceita drops do schema lateral (mesmos formatos que Mapper, Filter, etc.).
  // Funciona tanto no botão vazio quanto no chip já preenchido (substitui).
  const [dragOver, setDragOver] = useState(false)
  const fallbackNodeId = upstreamOutputs[0]?.nodeId ?? null

  function handleDragOver(e: React.DragEvent) {
    if (
      e.dataTransfer.types.includes(FIELD_REF_TYPE) ||
      e.dataTransfer.types.includes(FIELD_DRAG_TYPE)
    ) {
      e.preventDefault()
      e.dataTransfer.dropEffect = "copy"
      setDragOver(true)
    }
  }
  function handleDragLeave() {
    setDragOver(false)
  }
  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    const tpl = buildTemplateFromDrop(e, fallbackNodeId)
    if (tpl) {
      onChange(tpl)
      setOpen(false)
    }
  }

  const popover =
    open && pos && typeof document !== "undefined"
      ? createPortal(
          <div
            ref={popoverRef}
            role="listbox"
            className="fixed z-[1000] flex max-h-80 flex-col overflow-hidden rounded-lg border border-border bg-popover shadow-xl"
            style={{ top: pos.top, left: pos.left, width: pos.width }}
          >
            <p className="shrink-0 border-b border-border bg-muted/30 px-3 py-1.5 text-[10px] leading-relaxed text-muted-foreground/80">
              Selecione um valor escalar de um nó anterior. Vai pegar a primeira
              linha do dataset desse nó.
            </p>
            <div className="min-h-0 flex-1 overflow-y-auto p-1">
              {sources.length === 0 && (
                <p className="px-3 py-3 text-[11px] italic text-muted-foreground">
                  Nenhum nó anterior com dados disponíveis ainda. Execute o
                  fluxo até aqui pra ver os campos.
                </p>
              )}
              {sources.map((src) => (
                <div key={src.nodeId} className="mb-1 last:mb-0">
                  <p className="px-2 py-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                    {src.label}
                  </p>
                  {src.columns.map((col) => {
                    const isCurrent =
                      parsed?.nodeId === src.nodeId && parsed?.col === col
                    return (
                      <button
                        key={col}
                        type="button"
                        onClick={() => pick(src.nodeId, col)}
                        className={cn(
                          "flex w-full items-center gap-1.5 rounded-md px-2 py-1 text-left text-[11px] transition-colors",
                          isCurrent
                            ? "bg-primary/15 text-primary"
                            : "text-foreground hover:bg-primary/10",
                        )}
                      >
                        <Link2
                          className={cn(
                            "size-3 shrink-0",
                            isCurrent
                              ? "text-primary"
                              : "text-muted-foreground/40",
                          )}
                        />
                        <span className="truncate">{col}</span>
                      </button>
                    )
                  })}
                </div>
              ))}
            </div>
          </div>,
          document.body,
        )
      : null

  // Modo chip — valor linkado
  if (parsed) {
    return (
      <div
        className={cn(
          "flex min-w-0 items-center gap-1.5 rounded-md transition-colors",
          dragOver && "ring-2 ring-primary ring-offset-1",
        )}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
      >
        <span
          className={cn(
            "flex size-7 shrink-0 items-center justify-center rounded-md border",
            parsed.found
              ? "border-primary/40 bg-primary/10 text-primary"
              : "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
          )}
          title={parsed.found ? "Valor linkado" : "Nó de origem não encontrado"}
        >
          <Link2 className="size-3.5" />
        </span>
        <button
          ref={triggerRef}
          type="button"
          onClick={() => setOpen((v) => !v)}
          className={cn(
            "inline-flex h-7 min-w-0 flex-1 items-center gap-1.5 rounded-md px-2 text-[11px] font-semibold transition-colors",
            parsed.found
              ? "bg-primary/12 text-primary hover:bg-primary/20"
              : "bg-amber-500/10 text-amber-700 hover:bg-amber-500/20 dark:text-amber-300",
          )}
          title="Clique para alterar (ou arraste outro campo aqui)"
        >
          <span className="truncate font-medium opacity-70">
            {parsed.label}
          </span>
          <span className="opacity-40">·</span>
          <span className="truncate">{parsed.col}</span>
          <ChevronDown className="ml-auto size-3 shrink-0 opacity-50" />
        </button>
        <button
          type="button"
          onClick={() => onChange("")}
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
          aria-label="Limpar"
        >
          <Trash2 className="size-3" />
        </button>
        {popover}
      </div>
    )
  }

  // Modo picker — sem valor linkado
  return (
    <>
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        onDragOver={handleDragOver}
        onDragLeave={handleDragLeave}
        onDrop={handleDrop}
        className={cn(
          "flex h-8 w-full items-center gap-2 rounded-md border border-dashed px-2.5 text-[11px] font-medium transition-colors",
          dragOver
            ? "border-primary bg-primary/5 text-primary"
            : "border-border bg-background text-muted-foreground hover:border-foreground/30 hover:text-foreground",
        )}
      >
        <Link2 className="size-3" />
        <span className="flex-1 text-left">
          {dragOver
            ? "Soltar campo aqui"
            : "Arraste um campo ou clique para selecionar"}
        </span>
        <ChevronDown className="size-3 opacity-60" />
      </button>
      {popover}
    </>
  )
}

export function RecordIdConfig({ data, onUpdate }: RecordIdConfigProps) {
  const upstreamFields = useUpstreamFields()

  const idColumn = (data.id_column as string) ?? "id"
  // ``start_at`` aceita ``number`` (modo fixo) ou ``string`` com template
  // ``{{...}}`` (modo linkado, resolvido em runtime). Mantemos os dois
  // estados em paralelo via refs locais para que alternar o toggle não
  // perca o que o usuário tinha digitado no outro modo.
  const startAtRaw = data.start_at
  const isLinked = typeof startAtRaw === "string"
  const startAtFixed = typeof startAtRaw === "number" ? startAtRaw : 1
  const startAtTemplate = typeof startAtRaw === "string" ? startAtRaw : ""
  const startAtOffset = (data.start_at_offset as number) ?? 0
  // Memoria do "outro modo" pro toggle ser não-destrutivo. useRef para
  // sobreviver entre renders sem disparar re-render quando muda.
  const lastFixedRef = useRef<number>(typeof startAtRaw === "number" ? startAtRaw : 1)
  const lastTemplateRef = useRef<string>(typeof startAtRaw === "string" ? startAtRaw : "")
  if (typeof startAtRaw === "number") lastFixedRef.current = startAtRaw
  if (typeof startAtRaw === "string") lastTemplateRef.current = startAtRaw
  const partitionBy: string[] = Array.isArray(data.partition_by)
    ? (data.partition_by as string[])
    : []
  const orderBy: OrderByItem[] = Array.isArray(data.order_by)
    ? (data.order_by as unknown[]).map(normalizeOrderBy)
    : []

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  // --- Partition by ---
  function addPartitionField(field?: string) {
    if (field && partitionBy.includes(field)) return
    update({ partition_by: [...partitionBy, field ?? ""] })
  }

  function removePartitionField(i: number) {
    update({ partition_by: partitionBy.filter((_, idx) => idx !== i) })
  }

  function updatePartitionField(i: number, val: string) {
    update({ partition_by: partitionBy.map((v, idx) => (idx === i ? val : v)) })
  }

  function handlePartitionDrop(e: React.DragEvent) {
    e.preventDefault()
    const f = e.dataTransfer.getData(FIELD_DRAG_TYPE)
    if (f) addPartitionField(f)
  }

  // --- Order by ---
  function addOrderBy(field?: string) {
    update({ order_by: [...orderBy, { column: field ?? "", direction: "asc" }] })
  }

  function removeOrderBy(i: number) {
    update({ order_by: orderBy.filter((_, idx) => idx !== i) })
  }

  function updateOrderBy(i: number, patch: Partial<OrderByItem>) {
    update({ order_by: orderBy.map((ob, idx) => (idx === i ? { ...ob, ...patch } : ob)) })
  }

  function handleOrderByDrop(e: React.DragEvent) {
    e.preventDefault()
    const f = e.dataTransfer.getData(FIELD_DRAG_TYPE)
    if (f) addOrderBy(f)
  }

  return (
    <div className="space-y-4">
      {/* ID column name */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Nome da coluna de ID
        </label>
        <input
          type="text"
          value={idColumn}
          onChange={(e) => update({ id_column: e.target.value || "id" })}
          placeholder="id"
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Start at */}
      <div className="space-y-1.5">
        <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Iniciar em
          <HelpTip>
            Defina o número inicial da sequência.<br />
            <br />
            <strong>Fixo:</strong> um número direto (ex.: <code>1000</code>).
            <br />
            <strong>Linkar valor:</strong> referencie um valor calculado em
            outro nó. Útil para retomar uma sequência existente — ex.: um nó
            SQL que retorna <code>MAX(id)</code> e aqui você usa esse valor com
            offset <code>+1</code> para continuar a numeração.
          </HelpTip>
        </label>

        {/* Toggle Fixo / Linkado */}
        <div className="flex gap-1 rounded-md border border-border bg-muted/30 p-0.5">
          <button
            type="button"
            onClick={() => update({ start_at: lastFixedRef.current })}
            className={cn(
              "flex flex-1 items-center justify-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors",
              !isLinked
                ? "bg-background text-primary shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Hash className="size-3" />
            Fixo
          </button>
          <button
            type="button"
            onClick={() => update({ start_at: lastTemplateRef.current })}
            className={cn(
              "flex flex-1 items-center justify-center gap-1 rounded px-2 py-1 text-[11px] font-medium transition-colors",
              isLinked
                ? "bg-background text-primary shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Link2 className="size-3" />
            Linkar valor
          </button>
        </div>

        {!isLinked ? (
          <input
            type="number"
            min={1}
            value={startAtFixed}
            onChange={(e) =>
              update({ start_at: parseInt(e.target.value, 10) || 1 })
            }
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
          />
        ) : (
          <div className="space-y-1.5">
            <UpstreamLinkPicker
              template={startAtTemplate}
              onChange={(v) => update({ start_at: v })}
            />
            <div className="flex items-center gap-2">
              <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted-foreground/70">
                Somar offset
              </span>
              <input
                type="number"
                value={startAtOffset}
                onChange={(e) =>
                  update({ start_at_offset: parseInt(e.target.value, 10) || 0 })
                }
                className="h-7 w-20 rounded-md border border-input bg-background px-2 text-xs tabular-nums text-foreground outline-none focus:ring-1 focus:ring-primary"
              />
              <span className="text-[10px] text-muted-foreground/60">
                (ex.: <code>1</code> para começar logo depois do valor recebido)
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Partition by */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Reiniciar por grupo (Partition By)
        </label>
        <div className="space-y-1.5">
          {partitionBy.map((col, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <FieldChipPicker
                  value={col}
                  onChange={(v) => updatePartitionField(i, v)}
                  upstreamFields={upstreamFields}
                  placeholder="coluna de grupo"
                />
              </div>
              <button
                type="button"
                onClick={() => removePartitionField(i)}
                className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                aria-label="Remover grupo"
              >
                <Trash2 className="size-3" />
              </button>
            </div>
          ))}
        </div>
        <div
          onDragOver={(e) => {
            if (!e.dataTransfer.types.includes(FIELD_DRAG_TYPE)) return
            e.preventDefault()
            e.dataTransfer.dropEffect = "copy"
          }}
          onDrop={handlePartitionDrop}
          onClick={() => addPartitionField()}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed py-2 text-[11px] font-medium transition-all",
            "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
          <span className="text-muted-foreground/60">Arraste um campo</span>
          <span className="text-muted-foreground/30">ou</span>
          <span className="flex items-center gap-1">
            <Plus className="size-3" />
            Adicionar grupo
          </span>
        </div>
        <p className="mt-1.5 text-[10px] text-muted-foreground/70">
          Opcional. Quando definido, a numeração recomeça em cada combinação de valores.
        </p>
      </div>

      {/* Order by */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Ordenar antes de numerar (Order By)
        </label>
        <div className="space-y-1.5">
          {orderBy.map((ob, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <FieldChipPicker
                  value={ob.column}
                  onChange={(v) => updateOrderBy(i, { column: v })}
                  upstreamFields={upstreamFields}
                  placeholder="coluna"
                />
              </div>
              <button
                type="button"
                onClick={() =>
                  updateOrderBy(i, { direction: ob.direction === "asc" ? "desc" : "asc" })
                }
                className={cn(
                  "flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium transition-colors",
                  ob.direction === "asc"
                    ? "bg-primary/10 text-primary"
                    : "bg-muted text-muted-foreground hover:text-foreground",
                )}
                title={ob.direction === "asc" ? "Crescente" : "Decrescente"}
              >
                {ob.direction === "asc" ? (
                  <ArrowUp className="size-3" />
                ) : (
                  <ArrowDown className="size-3" />
                )}
                {ob.direction.toUpperCase()}
              </button>
              <button
                type="button"
                onClick={() => removeOrderBy(i)}
                className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                aria-label="Remover coluna"
              >
                <Trash2 className="size-3" />
              </button>
            </div>
          ))}
        </div>
        <div
          onDragOver={(e) => {
            if (!e.dataTransfer.types.includes(FIELD_DRAG_TYPE)) return
            e.preventDefault()
            e.dataTransfer.dropEffect = "copy"
          }}
          onDrop={handleOrderByDrop}
          onClick={() => addOrderBy()}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-md border border-dashed py-2 text-[11px] font-medium transition-all",
            "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
          <span className="text-muted-foreground/60">Arraste um campo</span>
          <span className="text-muted-foreground/30">ou</span>
          <span className="flex items-center gap-1">
            <Plus className="size-3" />
            Adicionar coluna de ordem
          </span>
        </div>
        <p className="mt-1.5 text-[10px] text-muted-foreground/70">
          Opcional. Sem ordenação, a sequência não é determinística.
        </p>
      </div>
    </div>
  )
}
