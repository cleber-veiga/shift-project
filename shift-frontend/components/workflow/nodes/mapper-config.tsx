"use client"

import { useCallback, useState } from "react"
import { ChevronDown, ChevronsDownUp, ChevronsUpDown, GripVertical, Plus, Sparkles, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import { ValueInput } from "@/components/workflow/value-input"
import { parseExprTokens } from "@/components/workflow/value-input"
import {
  mappingToParameterValue,
  parameterValueToMapping,
  type ParameterValue,
  type MapperMapping,
} from "@/lib/workflow/parameter-value"

// ─── Types ────────────────────────────────────────────────────────────────────

type FieldType = "string" | "integer" | "float" | "boolean" | "date" | "datetime"
type ValueType = "field" | "static" | "expression"

type SimpleTransformEntry = string
type ParamTransformEntry  = { id: string; params: Record<string, string> }
type TransformEntry       = SimpleTransformEntry | ParamTransformEntry

interface Mapping {
  target: string
  type: FieldType
  valueType: ValueType
  source?: string
  value?: string
  exprTemplate?: string
  transforms?: TransformEntry[]
  expression?: string
}

interface MapperConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ─── Config ───────────────────────────────────────────────────────────────────

const FIELD_TYPES: { value: FieldType; label: string }[] = [
  { value: "string",   label: "String"   },
  { value: "integer",  label: "Inteiro"  },
  { value: "float",    label: "Decimal"  },
  { value: "boolean",  label: "Booleano" },
  { value: "date",     label: "Data"     },
  { value: "datetime", label: "Datetime" },
]

interface TransformDef {
  id: string
  label: string
  apply: (expr: string, params?: Record<string, string>) => string
  hasParams?: boolean
  paramDefs?: { key: string; label: string; placeholder?: string }[]
}

function escapeRegexClass(chars: string): string {
  return chars.replace(/[-\]\\^]/g, "\\$&")
}

function escapeSql(s: string): string {
  return s.replace(/'/g, "''")
}

// SQL-level transforms — still needed to recompute expression for the backend.
//
// IMPORTANTE: REGEXP_REPLACE em DuckDB substitui apenas a PRIMEIRA ocorrencia
// quando o flag 'g' nao e passado. Todos os transforms baseados em regex
// abaixo precisam do quarto argumento 'g' pra remover/substituir TODAS as
// ocorrencias. Sem ele, "12.345.678/0001-90" -> only_digits vira "12345.678/0001-90".
const TRANSFORMS: TransformDef[] = [
  { id: "upper",          label: "Maiúsculo",        apply: (e) => `UPPER(${e})` },
  { id: "lower",          label: "Minúsculo",        apply: (e) => `LOWER(${e})` },
  { id: "trim",           label: "Sem espaços",      apply: (e) => `TRIM(${e})` },
  { id: "remove_special", label: "Remover especiais", apply: (e) => `REGEXP_REPLACE(${e}, '[^A-Za-z0-9 ]', '', 'g')` },
  { id: "only_digits",    label: "Somente dígitos",  apply: (e) => `REGEXP_REPLACE(${e}, '[^0-9]', '', 'g')` },
  {
    id: "remove_chars", label: "Remover caracteres", hasParams: true,
    paramDefs: [{ key: "chars", label: "Caracteres", placeholder: "ex: ( ) - / ." }],
    apply: (e, p) => {
      const chars = p?.chars ?? ""
      if (!chars) return e
      return `REGEXP_REPLACE(${e}, '[${escapeSql(escapeRegexClass(chars))}]', '', 'g')`
    },
  },
  {
    id: "replace", label: "Substituir", hasParams: true,
    paramDefs: [
      { key: "from", label: "De",  placeholder: "texto a substituir" },
      { key: "to",   label: "Por", placeholder: "vazio = remover"    },
    ],
    apply: (e, p) => `REPLACE(${e}, '${escapeSql(p?.from ?? "")}', '${escapeSql(p?.to ?? "")}')`,
  },
  {
    id: "truncate", label: "Truncar", hasParams: true,
    paramDefs: [{ key: "length", label: "Tamanho", placeholder: "ex: 3" }],
    apply: (e, p) => {
      const len = parseInt(p?.length ?? "0", 10)
      return len > 0 ? `LEFT(${e}, ${len})` : e
    },
  },
]

// ─── Pure helpers ─────────────────────────────────────────────────────────────

function entryId(e: TransformEntry): string {
  return typeof e === "string" ? e : e.id
}

function buildFieldExpression(source: string, transforms: TransformEntry[]): string | undefined {
  if (!transforms.length) return undefined
  let expr = `"${source}"`
  for (const entry of transforms) {
    const id     = entryId(entry)
    const params = typeof entry === "string" ? undefined : entry.params
    const t      = TRANSFORMS.find((t) => t.id === id)
    if (t) expr  = t.apply(expr, params)
  }
  return expr
}

function buildStaticExpression(value: string): string | undefined {
  return value ? `'${value.replace(/'/g, "''")}'` : undefined
}

const SYSTEM_VARS_SQL: Record<string, string> = {
  "$now":   "CURRENT_TIMESTAMP",
  "$today": "CURRENT_DATE",
}

function buildExpressionSql(template: string): string | undefined {
  if (!template.trim()) return undefined
  const TOKEN_RE = /(\{\{[^}]+\}\}|\$[a-zA-Z_]+)/g
  const parts: string[] = []
  let last = 0
  let match: RegExpExecArray | null
  while ((match = TOKEN_RE.exec(template)) !== null) {
    if (match.index > last) parts.push(`'${escapeSql(template.slice(last, match.index))}'`)
    const tok = match[1]
    if (tok.startsWith("{{")) {
      parts.push(`"${tok.slice(2, -2)}"`)
    } else {
      parts.push(SYSTEM_VARS_SQL[tok] ?? `'${escapeSql(tok)}'`)
    }
    last = match.index + tok.length
  }
  if (last < template.length) parts.push(`'${escapeSql(template.slice(last))}'`)
  if (parts.length === 0) return undefined
  if (parts.length === 1) return `CAST(${parts[0]} AS VARCHAR)`
  return parts.join(" || ")
}

/** Handles the very old `{ source, target }` format (no valueType). */
function normalise(raw: Record<string, unknown>): Mapping {
  if (raw.valueType) return raw as unknown as Mapping
  return {
    target:       String(raw.target  ?? ""),
    type:         "string",
    valueType:    "field",
    source:       String(raw.source  ?? ""),
    transforms:   [],
    exprTemplate: raw.exprTemplate ? String(raw.exprTemplate) : undefined,
    expression:   raw.expression   ? String(raw.expression)   : undefined,
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

const CARD_DRAG_TYPE  = "application/x-shift-card"
const FIELD_DRAG_TYPE = "application/x-shift-field"

export function MapperConfig({ data, onUpdate }: MapperConfigProps) {
  const upstreamFields = useUpstreamFields()
  const [isDragOver,  setIsDragOver]  = useState(false)
  const [collapsed,   setCollapsed]   = useState<Set<string>>(new Set())
  const [draggedIdx,  setDraggedIdx]  = useState<number | null>(null)
  const [dragOverIdx, setDragOverIdx] = useState<number | null>(null)

  const mappings: Mapping[] = Array.isArray(data.mappings)
    ? (data.mappings as Record<string, unknown>[]).map(normalise)
    : []

  const dropUnmapped = Boolean(data.drop_unmapped)

  const setMappings = useCallback(
    (next: Mapping[]) => onUpdate({ ...data, mappings: next }),
    [data, onUpdate],
  )

  // ─── Collapse ─────────────────────────────────────────────────────────────

  function collapseKey(m: Mapping, i: number) { return m.target || `__idx_${i}` }

  function toggleCollapse(m: Mapping, i: number) {
    const key = collapseKey(m, i)
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      return next
    })
  }

  // ─── Card reorder ─────────────────────────────────────────────────────────

  function handleCardDragStart(e: React.DragEvent, index: number) {
    e.dataTransfer.setData(CARD_DRAG_TYPE, String(index))
    e.dataTransfer.effectAllowed = "move"
    setDraggedIdx(index)
  }
  function handleCardDragEnd() { setDraggedIdx(null); setDragOverIdx(null) }
  function handleCardDragOver(e: React.DragEvent, index: number) {
    if (!e.dataTransfer.types.includes(CARD_DRAG_TYPE)) return
    e.preventDefault()
    setDragOverIdx(index)
  }
  function handleCardDrop(e: React.DragEvent, targetIndex: number) {
    if (!e.dataTransfer.types.includes(CARD_DRAG_TYPE)) return
    e.preventDefault()
    if (draggedIdx === null || draggedIdx === targetIndex) {
      setDraggedIdx(null); setDragOverIdx(null); return
    }
    const next = [...mappings]
    const [removed] = next.splice(draggedIdx, 1)
    next.splice(targetIndex, 0, removed)
    setMappings(next)
    setDraggedIdx(null); setDragOverIdx(null)
  }

  // ─── Mutations ────────────────────────────────────────────────────────────

  function recomputeExpression(m: Mapping): Mapping {
    let expression: string | undefined
    if (m.valueType === "field") {
      expression = m.source ? buildFieldExpression(m.source, m.transforms ?? []) : undefined
    } else if (m.valueType === "expression") {
      expression = buildExpressionSql(m.exprTemplate ?? "")
    } else {
      expression = buildStaticExpression(m.value ?? "")
    }
    return { ...m, expression }
  }

  function updateMapping(index: number, patch: Partial<Mapping>) {
    setMappings(mappings.map((m, i) => i === index ? recomputeExpression({ ...m, ...patch }) : m))
  }

  /** Converts a ParameterValue back to Mapping format, then recomputes SQL. */
  function updateMappingFromPV(index: number, pv: ParameterValue) {
    const m     = mappings[index]
    const patch = parameterValueToMapping(pv, m as MapperMapping)
    updateMapping(index, patch)
  }

  function addMapping() {
    setMappings([...mappings, { target: "", type: "string", valueType: "field", source: "" }])
  }
  function removeMapping(index: number) {
    setMappings(mappings.filter((_, i) => i !== index))
  }

  function autoMapAll() {
    // Skip fields already referenced as single-field mappings.
    const used = new Set(mappings.filter((m) => m.valueType === "field").map((m) => m.source))
    const next: Mapping[] = upstreamFields
      .filter((f) => !used.has(f))
      .map((f) => ({ target: f, type: "string" as FieldType, valueType: "field" as ValueType, source: f }))
    setMappings([...mappings, ...next])
  }

  // ─── Drop zone (bottom) ───────────────────────────────────────────────────

  function handleDropOnZone(e: React.DragEvent) {
    e.preventDefault()
    setIsDragOver(false)
    const field = e.dataTransfer.getData(FIELD_DRAG_TYPE)
    if (!field || mappings.some((m) => m.source === field)) return
    setMappings([...mappings, { target: field, type: "string", valueType: "field", source: field }])
  }

  // ─── Derived ──────────────────────────────────────────────────────────────

  const upstreamFieldObjs = upstreamFields.map((name) => ({ name }))

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">

      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={!dropUnmapped}
          onChange={(e) => onUpdate({ ...data, drop_unmapped: !e.target.checked })}
          className="size-3.5 rounded border-input accent-primary"
        />
        <span className="text-xs text-foreground">Incluir outros campos da entrada</span>
      </label>

      <div>
        {/* Header */}
        <div className="mb-2 flex items-center justify-between">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Campos
          </label>
          <div className="flex items-center gap-2">
            {mappings.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  const allCollapsed = mappings.every((m, i) => collapsed.has(collapseKey(m, i)))
                  setCollapsed(allCollapsed
                    ? new Set()
                    : new Set(mappings.map((m, i) => collapseKey(m, i))))
                }}
                className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {mappings.every((m, i) => collapsed.has(collapseKey(m, i)))
                  ? <><ChevronsUpDown className="size-3" /> Expandir todos</>
                  : <><ChevronsDownUp className="size-3" /> Minimizar todos</>}
              </button>
            )}
            {upstreamFields.length > 0 &&
              mappings.filter((m) => m.valueType === "field").length < upstreamFields.length && (
                <button
                  type="button"
                  onClick={autoMapAll}
                  className="flex items-center gap-1 text-[10px] font-medium text-primary transition-colors hover:text-primary/80"
                >
                  <Sparkles className="size-3" />
                  Mapear todos
                </button>
              )}
          </div>
        </div>

        {/* Cards */}
        <div className="space-y-2">
          {mappings.map((m, i) => {
            const isCollapsed  = collapsed.has(collapseKey(m, i))
            const isDragged    = draggedIdx === i
            const isDragTarget = dragOverIdx === i && draggedIdx !== null && draggedIdx !== i
            const activeLabels = (m.transforms ?? [])
              .map((e) => TRANSFORMS.find((t) => t.id === entryId(e))?.label)
              .filter(Boolean) as string[]

            return (
              <div
                key={i}
                className={cn(
                  "rounded-lg border bg-muted/20 transition-all",
                  isDragged    ? "opacity-40 border-dashed border-border" : "border-border",
                  isDragTarget && "ring-2 ring-primary ring-offset-1",
                )}
                onDragOver={(e) => handleCardDragOver(e, i)}
                onDragLeave={(e) => {
                  const related = e.relatedTarget as Node | null
                  if (related && e.currentTarget.contains(related)) return
                  if (dragOverIdx === i) setDragOverIdx(null)
                }}
                onDrop={(e) => handleCardDrop(e, i)}
              >
                {/* ── Row 1: grip + target + type + collapse + delete ── */}
                <div className="flex items-center gap-1.5 p-2.5">
                  <div
                    draggable
                    onDragStart={(e) => handleCardDragStart(e, i)}
                    onDragEnd={handleCardDragEnd}
                    title="Arrastar para reordenar"
                    className="flex size-5 shrink-0 cursor-grab items-center justify-center rounded text-muted-foreground/25 transition-colors hover:text-muted-foreground active:cursor-grabbing"
                  >
                    <GripVertical className="size-3.5" />
                  </div>

                  <input
                    type="text"
                    value={m.target}
                    onChange={(e) => updateMapping(i, { target: e.target.value })}
                    placeholder="nome_do_campo"
                    className="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs font-medium text-foreground outline-none placeholder:font-normal placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"
                  />
                  <select
                    value={m.type}
                    onChange={(e) => updateMapping(i, { type: e.target.value as FieldType })}
                    className="h-7 shrink-0 rounded-md border border-input bg-background px-1.5 text-[11px] text-muted-foreground outline-none focus:ring-1 focus:ring-primary"
                  >
                    {FIELD_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>

                  <button
                    type="button"
                    onClick={() => toggleCollapse(m, i)}
                    title={isCollapsed ? "Expandir" : "Minimizar"}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground/50 transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <ChevronDown className={cn("size-3.5 transition-transform duration-150", isCollapsed && "-rotate-90")} />
                  </button>

                  <button
                    type="button"
                    onClick={() => removeMapping(i)}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    aria-label="Remover campo"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>

                {/* ── Collapsed summary ── */}
                {isCollapsed && (
                  <div className="flex flex-wrap items-center gap-1.5 px-2.5 pb-2 -mt-1">
                    <span className="text-[10px] text-muted-foreground">
                      {m.valueType === "field"
                        ? (m.source || "—")
                        : m.valueType === "expression"
                          ? (m.exprTemplate
                              ? parseExprTokens(m.exprTemplate).map((tok, ti) =>
                                  tok.type === "text" ? (
                                    <span key={ti}>{tok.value}</span>
                                  ) : tok.type === "field" ? (
                                    <span key={ti} className="rounded bg-primary/15 px-1 py-px text-[9px] font-semibold text-primary">{tok.value}</span>
                                  ) : (
                                    <span key={ti} className="rounded bg-amber-500/15 px-1 py-px text-[9px] font-semibold text-amber-600 dark:text-amber-400">{tok.value}</span>
                                  ))
                              : "—")
                          : `"${m.value ?? ""}"`}
                    </span>
                    {activeLabels.length > 0 && (
                      <>
                        <span className="text-[10px] text-muted-foreground/30">·</span>
                        {activeLabels.map((label) => (
                          <span key={label} className="rounded-full bg-primary/10 px-1.5 py-px text-[9px] font-medium text-primary/70">
                            {label}
                          </span>
                        ))}
                      </>
                    )}
                  </div>
                )}

                {/* ── Expanded: ValueInput ── */}
                {!isCollapsed && (
                  <div className="px-2.5 pb-2.5">
                    <ValueInput
                      value={mappingToParameterValue(m as MapperMapping)}
                      onChange={(pv) => updateMappingFromPV(i, pv)}
                      upstreamFields={upstreamFieldObjs}
                      allowVariables={true}
                    />
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Drop zone / Add button */}
        <div
          onDragOver={(e) => {
            if (!e.dataTransfer.types.includes(FIELD_DRAG_TYPE)) return
            e.preventDefault()
            e.dataTransfer.dropEffect = "copy"
            setIsDragOver(true)
          }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDropOnZone}
          onClick={addMapping}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed py-3 text-[11px] font-medium transition-all",
            isDragOver
              ? "border-primary bg-primary/5 text-primary"
              : "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
          {isDragOver ? (
            <><GripVertical className="size-3.5" /> Soltar campo aqui</>
          ) : (
            <>
              <span className="text-muted-foreground/50">Arraste campos da entrada aqui</span>
              <span className="text-muted-foreground/30">ou</span>
              <span className="flex items-center gap-1">
                <Plus className="size-3" />
                Adicionar campo
              </span>
            </>
          )}
        </div>

        {upstreamFields.length === 0 && mappings.length === 0 && (
          <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground/70">
            Execute o nó anterior para ver os campos disponíveis automaticamente,
            ou adicione campos manualmente.
          </p>
        )}
      </div>
    </div>
  )
}
