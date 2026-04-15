"use client"

import { useCallback, useState } from "react"
import { GripVertical, Link2, Plus, Sparkles, TextCursorInput, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"

// ─── Types ────────────────────────────────────────────────────────────────────

type FieldType = "string" | "integer" | "float" | "boolean" | "date" | "datetime"
type ValueType = "field" | "static"

interface Mapping {
  target: string
  type: FieldType
  valueType: ValueType
  source?: string   // when valueType === "field"
  value?: string    // when valueType === "static"
  transforms?: string[]
  expression?: string // computed — sent to backend
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

const TRANSFORMS = [
  { id: "upper",          label: "Maiúsculo",        apply: (e: string) => `UPPER(${e})`                               },
  { id: "lower",          label: "Minúsculo",        apply: (e: string) => `LOWER(${e})`                               },
  { id: "trim",           label: "Sem espaços",      apply: (e: string) => `TRIM(${e})`                                },
  { id: "remove_special", label: "Remover especiais",apply: (e: string) => `REGEXP_REPLACE(${e}, '[^A-Za-z0-9 ]', '')` },
]

// ─── Pure helpers ─────────────────────────────────────────────────────────────

function buildFieldExpression(source: string, transforms: string[]): string | undefined {
  if (!transforms.length) return undefined
  let expr = `"${source}"`
  for (const id of transforms) {
    const t = TRANSFORMS.find((t) => t.id === id)
    if (t) expr = t.apply(expr)
  }
  return expr
}

function buildStaticExpression(value: string): string | undefined {
  return value ? `'${value.replace(/'/g, "''")}'` : undefined
}

/** Support legacy { source, target } format saved before this redesign. */
function normalise(raw: Record<string, unknown>): Mapping {
  if (raw.valueType) return raw as unknown as Mapping
  return {
    target:    String(raw.target  ?? ""),
    type:      "string",
    valueType: "field",
    source:    String(raw.source  ?? ""),
    transforms: [],
    expression: raw.expression ? String(raw.expression) : undefined,
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

export function MapperConfig({ data, onUpdate }: MapperConfigProps) {
  const upstreamFields = useUpstreamFields()
  const [isDragOver, setIsDragOver] = useState(false)

  const mappings: Mapping[] = Array.isArray(data.mappings)
    ? (data.mappings as Record<string, unknown>[]).map(normalise)
    : []

  const dropUnmapped = Boolean(data.drop_unmapped)

  const setMappings = useCallback(
    (next: Mapping[]) => onUpdate({ ...data, mappings: next }),
    [data, onUpdate],
  )

  // ─── Mutation helpers ──────────────────────────────────────────────────────

  function recomputeExpression(m: Mapping): Mapping {
    const expression =
      m.valueType === "field"
        ? m.source ? buildFieldExpression(m.source, m.transforms ?? []) : undefined
        : buildStaticExpression(m.value ?? "")
    return { ...m, expression }
  }

  function updateMapping(index: number, patch: Partial<Mapping>) {
    setMappings(
      mappings.map((m, i) =>
        i === index ? recomputeExpression({ ...m, ...patch }) : m,
      ),
    )
  }

  function toggleTransform(index: number, id: string) {
    const m = mappings[index]
    const current = m.transforms ?? []
    const next = current.includes(id) ? current.filter((t) => t !== id) : [...current, id]
    updateMapping(index, { transforms: next })
  }

  function addMapping() {
    setMappings([...mappings, { target: "", type: "string", valueType: "field", source: "" }])
  }

  function removeMapping(index: number) {
    setMappings(mappings.filter((_, i) => i !== index))
  }

  function autoMapAll() {
    const used = new Set(mappings.map((m) => m.source))
    const next: Mapping[] = upstreamFields
      .filter((f) => !used.has(f))
      .map((f) => ({ target: f, type: "string" as FieldType, valueType: "field" as ValueType, source: f }))
    setMappings([...mappings, ...next])
  }

  // ─── Drag & Drop ──────────────────────────────────────────────────────────

  function getField(e: React.DragEvent) {
    return e.dataTransfer.getData("application/x-shift-field")
  }

  function handleDropOnZone(e: React.DragEvent) {
    e.preventDefault()
    setIsDragOver(false)
    const field = getField(e)
    if (!field || mappings.some((m) => m.source === field)) return
    setMappings([...mappings, { target: field, type: "string", valueType: "field", source: field }])
  }

  function handleDropOnValue(e: React.DragEvent, index: number) {
    e.preventDefault()
    e.stopPropagation()
    const field = getField(e)
    if (!field) return
    const m = mappings[index]
    const autoTarget = !m.target || m.target === m.source
    updateMapping(index, {
      source: field,
      target: autoTarget ? field : m.target,
      valueType: "field",
    })
  }

  const usedSources = new Set(
    mappings.filter((m) => m.valueType === "field").map((m) => m.source),
  )

  // ─── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">

      {/* Node name */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Nome do nó
        </label>
        <input
          type="text"
          value={(data.label as string) ?? ""}
          onChange={(e) => onUpdate({ ...data, label: e.target.value })}
          placeholder="Nome personalizado..."
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Include other fields */}
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={!dropUnmapped}
          onChange={(e) => onUpdate({ ...data, drop_unmapped: !e.target.checked })}
          className="size-3.5 rounded border-input accent-primary"
        />
        <span className="text-xs text-foreground">Incluir outros campos da entrada</span>
      </label>

      {/* Fields section */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Campos
          </label>
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

        {/* Cards */}
        <div className="space-y-2">
          {mappings.map((m, i) => (
            <div
              key={i}
              className="rounded-lg border border-border bg-muted/20 p-2.5 space-y-2"
            >
              {/* ── Row 1: target name + type + delete ── */}
              <div className="flex items-center gap-1.5">
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
                  onClick={() => removeMapping(i)}
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  aria-label="Remover campo"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>

              {/* ── Row 2: value type toggle + value input ── */}
              <div
                className="flex items-center gap-1.5"
                onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy" }}
                onDrop={(e) => handleDropOnValue(e, i)}
              >
                {/* Toggle: field ↔ static */}
                <button
                  type="button"
                  title={m.valueType === "field" ? "Mudar para valor fixo" : "Mudar para campo"}
                  onClick={() =>
                    updateMapping(i, {
                      valueType: m.valueType === "field" ? "static" : "field",
                      source: "",
                      value: "",
                      transforms: [],
                    })
                  }
                  className={cn(
                    "flex size-7 shrink-0 items-center justify-center rounded-md border transition-colors",
                    m.valueType === "field"
                      ? "border-primary/40 bg-primary/10 text-primary"
                      : "border-border bg-background text-muted-foreground hover:text-foreground",
                  )}
                >
                  {m.valueType === "field"
                    ? <Link2 className="size-3.5" />
                    : <TextCursorInput className="size-3.5" />
                  }
                </button>

                {m.valueType === "field" ? (
                  upstreamFields.length > 0 ? (
                    <select
                      value={m.source ?? ""}
                      onChange={(e) => updateMapping(i, { source: e.target.value })}
                      className={cn(
                        "h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary",
                        m.source ? "text-foreground" : "text-muted-foreground",
                      )}
                    >
                      <option value="">Selecionar campo de entrada...</option>
                      {upstreamFields.map((f) => (
                        <option
                          key={f}
                          value={f}
                          disabled={usedSources.has(f) && f !== m.source}
                        >
                          {f}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={m.source ?? ""}
                      onChange={(e) => updateMapping(i, { source: e.target.value })}
                      placeholder="arraste ou digite o campo..."
                      className="h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                    />
                  )
                ) : (
                  <input
                    type="text"
                    value={m.value ?? ""}
                    onChange={(e) => updateMapping(i, { value: e.target.value })}
                    placeholder="valor fixo..."
                    className="h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                  />
                )}
              </div>

              {/* ── Row 3: transform chips (field mode only) ── */}
              {m.valueType === "field" && m.source && (
                <div className="flex flex-wrap gap-1 pt-0.5">
                  {TRANSFORMS.map((t) => {
                    const active = (m.transforms ?? []).includes(t.id)
                    return (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => toggleTransform(i, t.id)}
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-[10px] font-medium transition-colors",
                          active
                            ? "border-primary bg-primary/10 text-primary"
                            : "border-border text-muted-foreground/60 hover:border-foreground/30 hover:text-foreground",
                        )}
                      >
                        {t.label}
                      </button>
                    )
                  })}
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Drop zone / Add button */}
        <div
          onDragOver={(e) => { e.preventDefault(); e.dataTransfer.dropEffect = "copy"; setIsDragOver(true) }}
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
            <>
              <GripVertical className="size-3.5" />
              Soltar campo aqui
            </>
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
