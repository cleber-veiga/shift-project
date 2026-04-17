"use client"

import { useEffect, useMemo, useRef, useState } from "react"
import { ChevronDown, Plus, Search, Trash2, X } from "lucide-react"
import type {
  CompositeBlueprint,
  CompositeFkMapItem,
  CompositeTableStep,
  CreateCustomNodeDefinitionPayload,
  CustomNodeDefinition,
  CustomNodeFormField,
  CustomNodeFormSchema,
  UpdateCustomNodeDefinitionPayload,
} from "@/lib/auth"
import { getNodeIcon, ICON_NAMES } from "@/lib/workflow/node-icons"
import { cn } from "@/lib/utils"

// ─── Constants ──────────────────────────────────────────────────────────────

const CATEGORY_OPTIONS = [
  { value: "trigger", label: "Gatilho", swatch: "bg-amber-500" },
  { value: "input", label: "Entrada", swatch: "bg-blue-500" },
  { value: "transform", label: "Transformação", swatch: "bg-violet-500" },
  { value: "decision", label: "Decisão", swatch: "bg-orange-500" },
  { value: "output", label: "Saída", swatch: "bg-emerald-500" },
  { value: "ai", label: "IA", swatch: "bg-pink-500" },
]

const COLOR_PRESETS = [
  "#f59e0b", // amber
  "#3b82f6", // blue
  "#8b5cf6", // violet
  "#f97316", // orange
  "#10b981", // emerald
  "#ec4899", // pink
  "#ef4444", // red
  "#14b8a6", // teal
  "#eab308", // yellow
  "#6366f1", // indigo
  "#64748b", // slate
  "#0f172a", // near-black
]

const DEFAULT_BLUEPRINT: CompositeBlueprint = {
  tables: [
    {
      alias: "header",
      table: "",
      role: "header",
      fk_map: [],
      cardinality: "one",
      columns: [],
      returning: [],
    },
  ],
}

// ─── Reusable: ChipList ─────────────────────────────────────────────────────

interface ChipListProps {
  values: string[]
  onChange: (next: string[]) => void
  placeholder: string
  ariaLabel: string
}

function ChipList({ values, onChange, placeholder, ariaLabel }: ChipListProps) {
  const [draft, setDraft] = useState("")

  function commitDraft() {
    const v = draft.trim()
    if (!v) return
    if (values.includes(v)) {
      setDraft("")
      return
    }
    onChange([...values, v])
    setDraft("")
  }

  function removeAt(idx: number) {
    onChange(values.filter((_, i) => i !== idx))
  }

  return (
    <div
      className="flex min-h-[34px] flex-wrap items-center gap-1 rounded-md border border-input bg-background px-1.5 py-1 focus-within:ring-2 focus-within:ring-ring"
      aria-label={ariaLabel}
    >
      {values.map((v, i) => (
        <span
          key={`${v}-${i}`}
          className="inline-flex items-center gap-1 rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-foreground"
        >
          {v}
          <button
            type="button"
            onClick={() => removeAt(i)}
            className="text-muted-foreground hover:text-destructive"
            aria-label={`Remover ${v}`}
          >
            <X className="size-3" />
          </button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === ",") {
            e.preventDefault()
            commitDraft()
          } else if (e.key === "Backspace" && !draft && values.length > 0) {
            removeAt(values.length - 1)
          }
        }}
        onBlur={commitDraft}
        placeholder={values.length === 0 ? placeholder : ""}
        className="min-w-[80px] flex-1 bg-transparent px-1 text-[12px] text-foreground outline-none placeholder:text-muted-foreground"
      />
    </div>
  )
}

// ─── Reusable: IconPicker ───────────────────────────────────────────────────

interface IconPickerProps {
  value: string
  onChange: (name: string) => void
  color?: string
}

function IconPicker({ value, onChange, color }: IconPickerProps) {
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState("")
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener("mousedown", onClick)
    return () => document.removeEventListener("mousedown", onClick)
  }, [open])

  const filtered = useMemo(() => {
    if (!search.trim()) return ICON_NAMES
    const t = search.toLowerCase()
    return ICON_NAMES.filter((n) => n.toLowerCase().includes(t))
  }, [search])

  const SelectedIcon = getNodeIcon(value || "Database")
  const hasValue = value && ICON_NAMES.includes(value)

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex h-9 w-full items-center gap-2 rounded-md border border-input bg-background px-2.5 text-sm outline-none transition focus:ring-2 focus:ring-ring"
      >
        <span
          className="flex size-6 shrink-0 items-center justify-center rounded"
          style={
            color && color.trim()
              ? { backgroundColor: `${color}20`, color }
              : { backgroundColor: "hsl(var(--muted))" }
          }
        >
          <SelectedIcon className={cn("size-3.5", !color && "text-muted-foreground")} />
        </span>
        <span className={cn("flex-1 truncate text-left", !hasValue && "text-muted-foreground")}>
          {hasValue ? value : "Selecionar ícone..."}
        </span>
        <ChevronDown className="size-3.5 text-muted-foreground" />
      </button>

      {open && (
        <div className="absolute left-0 top-full z-20 mt-1 w-[320px] rounded-lg border border-border bg-card p-2 shadow-xl">
          <label className="flex h-8 items-center gap-2 rounded-md border border-input bg-background px-2">
            <Search className="size-3.5 text-muted-foreground" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar ícone..."
              className="w-full bg-transparent text-xs outline-none placeholder:text-muted-foreground"
              autoFocus
            />
          </label>

          <div className="mt-2 grid max-h-[260px] grid-cols-8 gap-1 overflow-y-auto">
            {filtered.map((name) => {
              const Icon = getNodeIcon(name)
              const isSel = name === value
              return (
                <button
                  key={name}
                  type="button"
                  onClick={() => {
                    onChange(name)
                    setOpen(false)
                  }}
                  title={name}
                  className={cn(
                    "flex aspect-square items-center justify-center rounded-md border transition-colors",
                    isSel
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-transparent text-muted-foreground hover:border-border hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icon className="size-4" />
                </button>
              )
            })}
            {filtered.length === 0 && (
              <p className="col-span-8 py-4 text-center text-xs text-muted-foreground">
                Nenhum ícone encontrado
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Reusable: ColorPicker ──────────────────────────────────────────────────

interface ColorPickerProps {
  value: string
  onChange: (color: string) => void
}

function ColorPicker({ value, onChange }: ColorPickerProps) {
  const normalized = (value || "").trim()
  return (
    <div className="flex h-9 items-center gap-1.5 rounded-md border border-input bg-background px-1.5">
      <input
        type="color"
        value={normalized && /^#[0-9a-f]{6}$/i.test(normalized) ? normalized : "#8b5cf6"}
        onChange={(e) => onChange(e.target.value)}
        aria-label="Selecionar cor"
        className="size-6 shrink-0 cursor-pointer rounded border border-border bg-transparent"
      />
      <div className="flex flex-1 flex-wrap items-center gap-1">
        {COLOR_PRESETS.map((c) => (
          <button
            key={c}
            type="button"
            onClick={() => onChange(c)}
            aria-label={`Cor ${c}`}
            className={cn(
              "size-4 rounded-full border transition-transform hover:scale-110",
              normalized.toLowerCase() === c.toLowerCase()
                ? "border-foreground ring-2 ring-ring"
                : "border-border",
            )}
            style={{ backgroundColor: c }}
          />
        ))}
        {normalized && (
          <button
            type="button"
            onClick={() => onChange("")}
            className="ml-auto text-[10px] text-muted-foreground hover:text-foreground"
          >
            limpar
          </button>
        )}
      </div>
    </div>
  )
}

// ─── BlueprintEditor ────────────────────────────────────────────────────────

interface BlueprintEditorProps {
  value: CompositeBlueprint
  onChange: (next: CompositeBlueprint) => void
  error?: string
}

function BlueprintEditor({ value, onChange, error }: BlueprintEditorProps) {
  function updateTable(idx: number, patch: Partial<CompositeTableStep>) {
    const tables = value.tables.map((t, i) => (i === idx ? { ...t, ...patch } : t))
    onChange({ tables })
  }

  function addTable() {
    const hasHeader = value.tables.some((t) => t.role === "header")
    const newTable: CompositeTableStep = {
      alias: hasHeader ? `child_${value.tables.length}` : "header",
      table: "",
      role: hasHeader ? "child" : "header",
      parent_alias: hasHeader ? value.tables[0]?.alias ?? null : null,
      fk_map: [],
      cardinality: "one",
      columns: [],
      returning: [],
    }
    onChange({ tables: [...value.tables, newTable] })
  }

  function removeTable(idx: number) {
    onChange({ tables: value.tables.filter((_, i) => i !== idx) })
  }

  function updateFkMap(tableIdx: number, fkIdx: number, patch: Partial<CompositeFkMapItem>) {
    const t = value.tables[tableIdx]
    if (!t) return
    const fk_map = t.fk_map.map((f, i) => (i === fkIdx ? { ...f, ...patch } : f))
    updateTable(tableIdx, { fk_map })
  }

  function addFkMap(tableIdx: number) {
    const t = value.tables[tableIdx]
    if (!t) return
    updateTable(tableIdx, {
      fk_map: [...t.fk_map, { child_column: "", parent_returning: "" }],
    })
  }

  function removeFkMap(tableIdx: number, fkIdx: number) {
    const t = value.tables[tableIdx]
    if (!t) return
    updateTable(tableIdx, {
      fk_map: t.fk_map.filter((_, i) => i !== fkIdx),
    })
  }

  const aliases = value.tables.map((t) => t.alias).filter(Boolean)

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">
          Tabelas do blueprint
        </span>
        <button
          type="button"
          onClick={addTable}
          className="inline-flex h-7 items-center gap-1 rounded-md border border-border bg-background px-2 text-xs font-medium hover:bg-accent"
        >
          <Plus className="size-3" />
          Tabela
        </button>
      </div>

      <div className="space-y-2.5">
        {value.tables.map((t, idx) => {
          const isHeader = t.role === "header"
          const parentOptions = aliases.filter((a) => a !== t.alias)
          return (
            <div
              key={idx}
              className="rounded-lg border border-border bg-muted/20 p-3"
            >
              <div className="mb-2 flex items-center gap-2">
                <span
                  className={cn(
                    "inline-flex rounded px-1.5 py-0.5 text-[9px] font-semibold uppercase",
                    isHeader
                      ? "bg-violet-500/10 text-violet-500"
                      : "bg-blue-500/10 text-blue-500",
                  )}
                >
                  {t.role}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  Tabela #{idx + 1}
                </span>
                {value.tables.length > 1 && (
                  <button
                    type="button"
                    onClick={() => removeTable(idx)}
                    className="ml-auto rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    aria-label="Remover tabela"
                  >
                    <Trash2 className="size-3.5" />
                  </button>
                )}
              </div>

              <div className="grid grid-cols-[110px_1fr_100px] gap-2">
                <label className="block">
                  <span className="mb-0.5 block text-[10px] font-medium text-muted-foreground">
                    Alias
                  </span>
                  <input
                    value={t.alias}
                    onChange={(e) => updateTable(idx, { alias: e.target.value })}
                    placeholder="header"
                    className="h-8 w-full rounded-md border border-input bg-background px-2 font-mono text-[12px] outline-none focus:ring-2 focus:ring-ring"
                  />
                </label>
                <label className="block">
                  <span className="mb-0.5 block text-[10px] font-medium text-muted-foreground">
                    Nome da tabela
                  </span>
                  <input
                    value={t.table}
                    onChange={(e) => updateTable(idx, { table: e.target.value })}
                    placeholder="NOTA"
                    className="h-8 w-full rounded-md border border-input bg-background px-2 font-mono text-[12px] outline-none focus:ring-2 focus:ring-ring"
                  />
                </label>
                <label className="block">
                  <span className="mb-0.5 block text-[10px] font-medium text-muted-foreground">
                    Papel
                  </span>
                  <select
                    value={t.role}
                    onChange={(e) =>
                      updateTable(idx, {
                        role: e.target.value as "header" | "child",
                        parent_alias:
                          e.target.value === "header" ? null : t.parent_alias,
                        fk_map: e.target.value === "header" ? [] : t.fk_map,
                      })
                    }
                    className="h-8 w-full rounded-md border border-input bg-background px-1.5 text-[12px] outline-none focus:ring-2 focus:ring-ring"
                  >
                    <option value="header">header</option>
                    <option value="child">child</option>
                  </select>
                </label>
              </div>

              <div className="mt-2 grid grid-cols-2 gap-2">
                <div>
                  <span className="mb-0.5 block text-[10px] font-medium text-muted-foreground">
                    Colunas gravadas
                  </span>
                  <ChipList
                    values={t.columns}
                    onChange={(columns) => updateTable(idx, { columns })}
                    placeholder="ex: ID, VALOR"
                    ariaLabel="Colunas da tabela"
                  />
                </div>
                <div>
                  <span className="mb-0.5 block text-[10px] font-medium text-muted-foreground">
                    Returning (colunas retornadas)
                  </span>
                  <ChipList
                    values={t.returning}
                    onChange={(returning) => updateTable(idx, { returning })}
                    placeholder="ex: ID"
                    ariaLabel="Colunas retornadas"
                  />
                </div>
              </div>

              {!isHeader && (
                <div className="mt-3 rounded-md border border-border/70 bg-background/50 p-2">
                  <div className="mb-1.5 flex items-center gap-2">
                    <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      Chave estrangeira
                    </span>
                    <label className="ml-auto flex items-center gap-1.5 text-[11px] text-muted-foreground">
                      Pai:
                      <select
                        value={t.parent_alias ?? ""}
                        onChange={(e) =>
                          updateTable(idx, { parent_alias: e.target.value || null })
                        }
                        className="h-7 rounded-md border border-input bg-background px-1.5 text-[11px] outline-none focus:ring-2 focus:ring-ring"
                      >
                        <option value="">—</option>
                        {parentOptions.map((a) => (
                          <option key={a} value={a}>
                            {a}
                          </option>
                        ))}
                      </select>
                    </label>
                  </div>

                  <div className="space-y-1.5">
                    {t.fk_map.map((fk, fkIdx) => {
                      const parent = value.tables.find(
                        (x) => x.alias === t.parent_alias,
                      )
                      const returningOptions = parent?.returning ?? []
                      return (
                        <div key={fkIdx} className="flex items-center gap-1.5">
                          <input
                            value={fk.child_column}
                            onChange={(e) =>
                              updateFkMap(idx, fkIdx, {
                                child_column: e.target.value,
                              })
                            }
                            placeholder="coluna_filha"
                            className="h-7 flex-1 rounded-md border border-input bg-background px-2 font-mono text-[11px] outline-none focus:ring-2 focus:ring-ring"
                          />
                          <span className="text-[10px] text-muted-foreground">←</span>
                          {returningOptions.length > 0 ? (
                            <select
                              value={fk.parent_returning}
                              onChange={(e) =>
                                updateFkMap(idx, fkIdx, {
                                  parent_returning: e.target.value,
                                })
                              }
                              className="h-7 flex-1 rounded-md border border-input bg-background px-1.5 font-mono text-[11px] outline-none focus:ring-2 focus:ring-ring"
                            >
                              <option value="">selecionar...</option>
                              {returningOptions.map((r) => (
                                <option key={r} value={r}>
                                  {r}
                                </option>
                              ))}
                            </select>
                          ) : (
                            <input
                              value={fk.parent_returning}
                              onChange={(e) =>
                                updateFkMap(idx, fkIdx, {
                                  parent_returning: e.target.value,
                                })
                              }
                              placeholder="coluna_pai"
                              className="h-7 flex-1 rounded-md border border-input bg-background px-2 font-mono text-[11px] outline-none focus:ring-2 focus:ring-ring"
                            />
                          )}
                          <button
                            type="button"
                            onClick={() => removeFkMap(idx, fkIdx)}
                            className="rounded p-1 text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                            aria-label="Remover FK"
                          >
                            <X className="size-3" />
                          </button>
                        </div>
                      )
                    })}
                    <button
                      type="button"
                      onClick={() => addFkMap(idx)}
                      className="inline-flex h-7 items-center gap-1 rounded-md border border-dashed border-border px-2 text-[11px] text-muted-foreground hover:bg-muted hover:text-foreground"
                    >
                      <Plus className="size-3" />
                      Adicionar FK
                    </button>
                  </div>
                </div>
              )}
            </div>
          )
        })}
      </div>

      {error && <p className="text-xs text-destructive">{error}</p>}
    </div>
  )
}

// ─── FormSchemaEditor ───────────────────────────────────────────────────────

interface FormSchemaEditorProps {
  blueprint: CompositeBlueprint
  value: CustomNodeFormField[]
  onChange: (fields: CustomNodeFormField[]) => void
}

function FormSchemaEditor({ blueprint, value, onChange }: FormSchemaEditorProps) {
  const allKeys = useMemo(() => {
    const keys: string[] = []
    for (const t of blueprint.tables) {
      for (const col of t.columns) keys.push(`${t.alias}.${col}`)
    }
    return keys
  }, [blueprint])

  const byKey = useMemo(() => {
    const m = new Map<string, CustomNodeFormField>()
    for (const f of value) m.set(f.key, f)
    return m
  }, [value])

  function upsert(key: string, patch: Partial<CustomNodeFormField>) {
    const existing = byKey.get(key)
    const next: CustomNodeFormField = existing
      ? { ...existing, ...patch }
      : { key, ...patch }

    // Normalize: drop empty strings
    if (next.label === "") next.label = null
    if (next.help === "") next.help = null
    if (next.default_upstream === "") next.default_upstream = null

    // Drop entry entirely if nothing customized
    const hasCustomization =
      (next.label ?? null) !== null ||
      (next.help ?? null) !== null ||
      next.required === true ||
      next.hidden === true ||
      (next.default_upstream ?? null) !== null

    if (!hasCustomization) {
      onChange(value.filter((f) => f.key !== key))
      return
    }

    if (existing) {
      onChange(value.map((f) => (f.key === key ? next : f)))
    } else {
      onChange([...value, next])
    }
  }

  if (allKeys.length === 0) {
    return (
      <p className="rounded-md border border-dashed border-border bg-muted/20 px-3 py-4 text-center text-xs text-muted-foreground">
        Adicione ao menos uma coluna no blueprint para configurar o formulário.
      </p>
    )
  }

  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-[minmax(110px,1fr)_minmax(110px,1fr)_minmax(110px,1fr)_60px_60px] gap-2 px-2 pb-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
        <span>Campo (alias.coluna)</span>
        <span>Rótulo exibido</span>
        <span>Sugestão (default upstream)</span>
        <span className="text-center">Obrig.</span>
        <span className="text-center">Oculto</span>
      </div>
      <div className="divide-y divide-border rounded-md border border-border bg-background">
        {allKeys.map((key) => {
          const field = byKey.get(key)
          return (
            <div
              key={key}
              className="grid grid-cols-[minmax(110px,1fr)_minmax(110px,1fr)_minmax(110px,1fr)_60px_60px] items-center gap-2 px-2 py-1.5"
            >
              <span className="truncate font-mono text-[11px] text-foreground" title={key}>
                {key}
              </span>
              <input
                value={field?.label ?? ""}
                onChange={(e) => upsert(key, { label: e.target.value })}
                placeholder="(padrão: nome da coluna)"
                className="h-7 w-full rounded-md border border-input bg-background px-2 text-[11px] outline-none focus:ring-2 focus:ring-ring"
              />
              <input
                value={field?.default_upstream ?? ""}
                onChange={(e) => upsert(key, { default_upstream: e.target.value })}
                placeholder="ex: total"
                className="h-7 w-full rounded-md border border-input bg-background px-2 font-mono text-[11px] outline-none focus:ring-2 focus:ring-ring"
              />
              <label className="flex items-center justify-center">
                <input
                  type="checkbox"
                  checked={field?.required === true}
                  onChange={(e) => upsert(key, { required: e.target.checked })}
                  className="rounded border-input"
                />
              </label>
              <label className="flex items-center justify-center">
                <input
                  type="checkbox"
                  checked={field?.hidden === true}
                  onChange={(e) => upsert(key, { hidden: e.target.checked })}
                  className="rounded border-input"
                />
              </label>
            </div>
          )
        })}
      </div>
      <p className="text-[10px] text-muted-foreground">
        Personalize como cada coluna aparece no editor do fluxo. Campos não
        customizados usam o padrão (rótulo = nome da coluna, não obrigatório,
        visível).
      </p>
    </div>
  )
}

// ─── Main Modal ─────────────────────────────────────────────────────────────

interface CustomNodeDefinitionFormModalProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  definition: CustomNodeDefinition | null
  scopeIds: { workspace_id?: string | null; project_id?: string | null }
  onSubmit: (
    payload: CreateCustomNodeDefinitionPayload | UpdateCustomNodeDefinitionPayload,
  ) => Promise<void>
}

export function CustomNodeDefinitionFormModal({
  open,
  onOpenChange,
  definition,
  scopeIds,
  onSubmit,
}: CustomNodeDefinitionFormModalProps) {
  const isEditing = definition !== null

  const [name, setName] = useState("")
  const [description, setDescription] = useState("")
  const [category, setCategory] = useState("output")
  const [icon, setIcon] = useState("Boxes")
  const [color, setColor] = useState("")
  const [version, setVersion] = useState<number>(1)
  const [isPublished, setIsPublished] = useState(false)
  const [blueprint, setBlueprint] = useState<CompositeBlueprint>(DEFAULT_BLUEPRINT)
  const [formFields, setFormFields] = useState<CustomNodeFormField[]>([])
  const [blueprintError, setBlueprintError] = useState("")
  const [submitting, setSubmitting] = useState(false)
  const [submitError, setSubmitError] = useState("")

  useEffect(() => {
    if (!open) return
    if (definition) {
      setName(definition.name)
      setDescription(definition.description ?? "")
      setCategory(definition.category)
      setIcon(definition.icon ?? "Boxes")
      setColor(definition.color ?? "")
      setVersion(definition.version)
      setIsPublished(definition.is_published)
      setBlueprint(definition.blueprint ?? DEFAULT_BLUEPRINT)
      setFormFields(definition.form_schema?.fields ?? [])
    } else {
      setName("")
      setDescription("")
      setCategory("output")
      setIcon("Boxes")
      setColor("")
      setVersion(1)
      setIsPublished(false)
      setBlueprint(DEFAULT_BLUEPRINT)
      setFormFields([])
    }
    setBlueprintError("")
    setSubmitError("")
  }, [open, definition])

  function validateBlueprint(): string {
    if (!blueprint.tables || blueprint.tables.length === 0) {
      return "Adicione ao menos uma tabela."
    }
    const aliases = new Set<string>()
    let headerCount = 0
    for (const t of blueprint.tables) {
      if (!t.alias.trim()) return "Toda tabela precisa de um alias."
      if (aliases.has(t.alias)) return `Alias duplicado: ${t.alias}.`
      aliases.add(t.alias)
      if (!t.table.trim()) return `Tabela "${t.alias}" sem nome real.`
      if (t.columns.length === 0)
        return `Tabela "${t.alias}" precisa ter ao menos uma coluna.`
      if (t.role === "header") headerCount++
      if (t.role === "child") {
        if (!t.parent_alias)
          return `Tabela filha "${t.alias}" precisa de um pai (parent_alias).`
        if (!aliases.has(t.parent_alias) && t.parent_alias !== t.alias) {
          // parent must be declared before (set already contains current; check others)
          const exists = blueprint.tables.some(
            (x) => x.alias === t.parent_alias && x.alias !== t.alias,
          )
          if (!exists)
            return `Pai "${t.parent_alias}" de "${t.alias}" não existe.`
        }
      }
    }
    if (headerCount !== 1) return "Exatamente uma tabela deve ter role=header."
    return ""
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setSubmitError("")

    const bpError = validateBlueprint()
    if (bpError) {
      setBlueprintError(bpError)
      return
    }
    setBlueprintError("")

    const form_schema: CustomNodeFormSchema | null =
      formFields.length > 0 ? { fields: formFields } : null

    setSubmitting(true)
    try {
      if (isEditing) {
        const payload: UpdateCustomNodeDefinitionPayload = {
          name,
          description: description || null,
          category,
          icon: icon || null,
          color: color || null,
          version,
          is_published: isPublished,
          blueprint,
          form_schema,
        }
        await onSubmit(payload)
      } else {
        const payload: CreateCustomNodeDefinitionPayload = {
          name,
          description: description || null,
          category,
          icon: icon || null,
          color: color || null,
          kind: "composite_insert",
          version,
          is_published: isPublished,
          blueprint,
          form_schema,
          workspace_id: scopeIds.workspace_id ?? null,
          project_id: scopeIds.project_id ?? null,
        }
        await onSubmit(payload)
      }
    } catch (err) {
      setSubmitError(err instanceof Error ? err.message : "Erro ao salvar.")
    } finally {
      setSubmitting(false)
    }
  }

  if (!open) return null

  const inputClass =
    "h-9 w-full rounded-md border border-input bg-background px-3 text-sm text-foreground outline-none transition focus:ring-2 focus:ring-ring placeholder:text-muted-foreground disabled:opacity-60"

  const PreviewIcon = getNodeIcon(icon || "Boxes")

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
      role="presentation"
      onClick={() => !submitting && onOpenChange(false)}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={isEditing ? "Editar nó personalizado" : "Novo nó personalizado"}
        className="flex max-h-[92vh] w-[min(780px,96vw)] flex-col rounded-2xl border border-border bg-card shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 border-b border-border px-5 py-4">
          <div
            className="flex size-9 shrink-0 items-center justify-center rounded-xl"
            style={
              color && color.trim()
                ? { backgroundColor: `${color}20`, color }
                : { backgroundColor: "hsl(var(--muted))" }
            }
          >
            <PreviewIcon className={cn("size-4", !color && "text-muted-foreground")} />
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-base font-semibold text-foreground">
              {isEditing
                ? `Editar: ${name || "nó personalizado"}`
                : "Novo nó personalizado"}
            </p>
            <p className="truncate text-xs text-muted-foreground">
              {isEditing
                ? "Ajuste o blueprint e salve para atualizar."
                : "Configure um nó composto reutilizável."}
            </p>
          </div>
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            className="rounded p-1 text-muted-foreground hover:bg-muted hover:text-foreground"
            aria-label="Fechar"
          >
            <X className="size-4" />
          </button>
        </div>

        <form
          onSubmit={handleSubmit}
          className="flex flex-1 flex-col gap-4 overflow-y-auto px-5 py-4"
        >
          {/* ── Identidade ── */}
          <section className="space-y-3">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Identidade
            </p>

            <div className="grid grid-cols-2 gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted-foreground">
                  Nome *
                </span>
                <input
                  required
                  type="text"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  maxLength={255}
                  placeholder="ex: Inserir Nota Fiscal"
                  className={inputClass}
                />
              </label>

              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted-foreground">
                  Categoria
                </span>
                <select
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  className={inputClass}
                >
                  {CATEGORY_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            <label className="block">
              <span className="mb-1 block text-xs font-medium text-muted-foreground">
                Descrição
              </span>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                maxLength={1024}
                placeholder="O que este nó faz? (opcional)"
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none transition focus:ring-2 focus:ring-ring"
              />
            </label>

            <div className="grid grid-cols-[1fr_1fr_80px] gap-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted-foreground">
                  Ícone
                </span>
                <IconPicker value={icon} onChange={setIcon} color={color} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted-foreground">
                  Cor
                </span>
                <ColorPicker value={color} onChange={setColor} />
              </label>
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-muted-foreground">
                  Versão
                </span>
                <input
                  required
                  type="number"
                  value={version}
                  onChange={(e) => setVersion(Number(e.target.value))}
                  min={1}
                  className={inputClass}
                />
              </label>
            </div>

            <label className="flex items-center gap-2 text-sm text-foreground">
              <input
                type="checkbox"
                checked={isPublished}
                onChange={(e) => setIsPublished(e.target.checked)}
                className="rounded border-input"
              />
              Publicado (disponível na paleta do editor)
            </label>
          </section>

          {/* ── Blueprint ── */}
          <section className="space-y-2">
            <div className="flex items-center gap-2">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                Blueprint
              </p>
              <span className="text-[10px] text-muted-foreground">
                Uma tabela <b>header</b> + tabelas <b>child</b> opcionais ligadas por FK.
              </span>
            </div>
            <BlueprintEditor
              value={blueprint}
              onChange={setBlueprint}
              error={blueprintError}
            />
          </section>

          {/* ── Form schema ── */}
          <section className="space-y-2">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              Formulário no editor (opcional)
            </p>
            <FormSchemaEditor
              blueprint={blueprint}
              value={formFields}
              onChange={setFormFields}
            />
          </section>

        </form>

        {submitError && (
          <div className="border-t border-destructive/20 bg-destructive/10 px-5 py-2.5 text-xs text-destructive">
            <b>Erro ao salvar:</b> {submitError}
          </div>
        )}

        <div className="flex justify-end gap-2 border-t border-border px-5 py-3">
          <button
            type="button"
            onClick={() => onOpenChange(false)}
            disabled={submitting}
            className="h-9 rounded-md border border-border bg-background px-4 text-sm font-medium hover:bg-accent disabled:opacity-60"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={submitting}
            className="h-9 rounded-md bg-foreground px-4 text-sm font-semibold text-background transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {submitting ? "Salvando..." : isEditing ? "Salvar" : "Criar"}
          </button>
        </div>
      </div>
    </div>
  )
}
