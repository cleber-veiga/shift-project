"use client"

import { useCallback, useRef, useState } from "react"
import { Braces, ChevronDown, ChevronsDownUp, ChevronsUpDown, GripVertical, Link2, Plus, Sparkles, TextCursorInput, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"

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
  source?: string      // when valueType === "field"
  value?: string       // when valueType === "static"
  exprTemplate?: string // when valueType === "expression" — e.g. "{{NUMERO}} {{COMPLEMENTO}}"
  transforms?: TransformEntry[]
  expression?: string  // computed SQL — sent to backend
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

interface ParamDef {
  key: string
  label: string
  placeholder?: string
}

interface TransformDef {
  id: string
  label: string
  description: string
  hasParams?: boolean
  paramDefs?: ParamDef[]
  apply: (expr: string, params?: Record<string, string>) => string
}

/** Escapa chars especiais dentro de uma classe de regex [...] */
function escapeRegexClass(chars: string): string {
  return chars.replace(/[-\]\\^]/g, "\\$&")
}

/** Escapa aspas simples para uso em strings SQL */
function escapeSql(s: string): string {
  return s.replace(/'/g, "''")
}

const TRANSFORMS: TransformDef[] = [
  {
    id: "upper",
    label: "Maiúsculo",
    description: 'Converte todos os caracteres para maiúsculo.\nEx: "silva" → "SILVA"',
    apply: (e) => `UPPER(${e})`,
  },
  {
    id: "lower",
    label: "Minúsculo",
    description: 'Converte todos os caracteres para minúsculo.\nEx: "SILVA" → "silva"',
    apply: (e) => `LOWER(${e})`,
  },
  {
    id: "trim",
    label: "Sem espaços",
    description: 'Remove espaços no início e no fim do valor.\nEx: "  abc  " → "abc"',
    apply: (e) => `TRIM(${e})`,
  },
  {
    id: "remove_special",
    label: "Remover especiais",
    description: 'Remove todos os caracteres especiais, mantendo apenas letras, números e espaços.\nEx: "R$ 1.500,00" → "R 150000"',
    apply: (e) => `REGEXP_REPLACE(${e}, '[^A-Za-z0-9 ]', '')`,
  },
  {
    id: "only_digits",
    label: "Somente dígitos",
    description: 'Remove tudo que não for número (0–9).\nEx: "(54) 9 9988-9051" → "54999889051"',
    apply: (e) => `REGEXP_REPLACE(${e}, '[^0-9]', '')`,
  },
  {
    id: "remove_chars",
    label: "Remover caracteres",
    description: 'Remove exatamente os caracteres que você definir.\nEx: chars "()- " em "(54) 9988-9051" → "5499889051"',
    hasParams: true,
    paramDefs: [
      { key: "chars", label: "Caracteres", placeholder: "ex: ( ) - / ." },
    ],
    apply: (e, p) => {
      const chars = p?.chars ?? ""
      if (!chars) return e
      const escaped = escapeSql(escapeRegexClass(chars))
      return `REGEXP_REPLACE(${e}, '[${escaped}]', '')`
    },
  },
  {
    id: "replace",
    label: "Substituir",
    description: 'Substitui um trecho do valor por outro. Deixe "Por" vazio para remover.\nEx: de "-" por "" em "123-456" → "123456"',
    hasParams: true,
    paramDefs: [
      { key: "from", label: "De",  placeholder: "texto a substituir" },
      { key: "to",   label: "Por", placeholder: "vazio = remover"    },
    ],
    apply: (e, p) => {
      const from = escapeSql(p?.from ?? "")
      const to   = escapeSql(p?.to   ?? "")
      return `REPLACE(${e}, '${from}', '${to}')`
    },
  },
  {
    id: "truncate",
    label: "Truncar",
    description: 'Limita o valor a um número máximo de caracteres.\nEx: tamanho 3 em "ABCDEF" → "ABC"',
    hasParams: true,
    paramDefs: [
      { key: "length", label: "Tamanho", placeholder: "ex: 3" },
    ],
    apply: (e, p) => {
      const len = parseInt(p?.length ?? "0", 10)
      if (!len || len <= 0) return e
      return `LEFT(${e}, ${len})`
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

// ─── System variables ────────────────────────────────────────────────────────

interface SystemVar {
  token: string
  label: string
  description: string
  sql: string
}

const SYSTEM_VARS: SystemVar[] = [
  { token: "$now", label: "$now", description: "Data e hora atual", sql: "CURRENT_TIMESTAMP" },
  { token: "$today", label: "$today", description: "Data atual (sem hora)", sql: "CURRENT_DATE" },
]

// ─── Expression builder ──────────────────────────────────────────────────────

/**
 * Converte um template de expressão com {{CAMPO}} e $var em SQL DuckDB.
 * Ex: "Rua {{NUMERO}} - {{COMPLEMENTO}} em $now"
 *   → 'Rua ' || "NUMERO" || ' - ' || "COMPLEMENTO" || ' em ' || CURRENT_TIMESTAMP
 */
function buildExpressionSql(template: string): string | undefined {
  if (!template.trim()) return undefined
  // Tokenize: split on {{FIELD}} and $var references
  const TOKEN_RE = /(\{\{[^}]+\}\}|\$[a-zA-Z_]+)/g
  const parts: string[] = []
  let last = 0
  let match: RegExpExecArray | null
  while ((match = TOKEN_RE.exec(template)) !== null) {
    if (match.index > last) {
      parts.push(`'${escapeSql(template.slice(last, match.index))}'`)
    }
    const tok = match[1]
    if (tok.startsWith("{{")) {
      const field = tok.slice(2, -2)
      parts.push(`"${field}"`)
    } else {
      const sysVar = SYSTEM_VARS.find((v) => v.token === tok)
      parts.push(sysVar ? sysVar.sql : `'${escapeSql(tok)}'`)
    }
    last = match.index + tok.length
  }
  if (last < template.length) {
    parts.push(`'${escapeSql(template.slice(last))}'`)
  }
  if (parts.length === 0) return undefined
  if (parts.length === 1) return `CAST(${parts[0]} AS VARCHAR)`
  return parts.join(" || ")
}

/** Support legacy { source, target } format saved before this redesign. */
function normalise(raw: Record<string, unknown>): Mapping {
  if (raw.valueType) return raw as unknown as Mapping
  return {
    target:       String(raw.target  ?? ""),
    type:         "string",
    valueType:    "field",
    source:       String(raw.source  ?? ""),
    transforms:   [],
    exprTemplate: raw.exprTemplate ? String(raw.exprTemplate) : undefined,
    expression:   raw.expression ? String(raw.expression) : undefined,
  }
}

// ─── Expression Input ────────────────────────────────────────────────────────

const EXPR_TOKEN_RE = /(\{\{[^}]+\}\}|\$[a-zA-Z_]+)/g

/** Parses an expression template into segments for rendering chips. */
function parseExprTokens(template: string): { type: "text" | "field" | "sysvar"; value: string }[] {
  const result: { type: "text" | "field" | "sysvar"; value: string }[] = []
  let last = 0
  let m: RegExpExecArray | null
  const re = new RegExp(EXPR_TOKEN_RE.source, "g")
  while ((m = re.exec(template)) !== null) {
    if (m.index > last) result.push({ type: "text", value: template.slice(last, m.index) })
    const tok = m[1]
    if (tok.startsWith("{{")) {
      result.push({ type: "field", value: tok.slice(2, -2) })
    } else {
      result.push({ type: "sysvar", value: tok })
    }
    last = m.index + tok.length
  }
  if (last < template.length) result.push({ type: "text", value: template.slice(last) })
  return result
}

interface ExpressionInputProps {
  value: string
  onChange: (value: string) => void
  upstreamFields: string[]
}

function ExpressionInput({ value, onChange, upstreamFields }: ExpressionInputProps) {
  const editRef = useRef<HTMLDivElement>(null)
  const [showVars, setShowVars] = useState(false)
  const [isDragOverExpr, setIsDragOverExpr] = useState(false)

  // Serialize contentEditable → template string
  function serialize(el: HTMLElement): string {
    let out = ""
    for (const node of Array.from(el.childNodes)) {
      if (node.nodeType === Node.TEXT_NODE) {
        out += node.textContent ?? ""
      } else if (node instanceof HTMLElement && node.dataset.token) {
        out += node.dataset.token
      }
    }
    return out
  }

  // Build DOM from template
  function renderToDOM(el: HTMLElement, template: string) {
    el.innerHTML = ""
    const tokens = parseExprTokens(template)
    for (const tok of tokens) {
      if (tok.type === "text") {
        el.appendChild(document.createTextNode(tok.value))
      } else {
        const chip = document.createElement("span")
        chip.contentEditable = "false"
        chip.dataset.token = tok.type === "field" ? `{{${tok.value}}}` : tok.value
        chip.className =
          tok.type === "field"
            ? "inline-flex items-center gap-0.5 rounded bg-primary/15 px-1 py-px mx-0.5 text-[10px] font-semibold text-primary align-baseline select-none cursor-default"
            : "inline-flex items-center gap-0.5 rounded bg-amber-500/15 px-1 py-px mx-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400 align-baseline select-none cursor-default"
        chip.textContent = tok.type === "field" ? tok.value : tok.value
        el.appendChild(chip)
      }
    }
  }

  // Initial render and sync when external value changes
  const lastSerialized = useRef(value)
  if (editRef.current && value !== lastSerialized.current) {
    renderToDOM(editRef.current, value)
    lastSerialized.current = value
  }

  function handleRef(el: HTMLDivElement | null) {
    (editRef as React.MutableRefObject<HTMLDivElement | null>).current = el
    if (el && !el.hasChildNodes()) {
      renderToDOM(el, value)
      lastSerialized.current = value
    }
  }

  function handleInput() {
    if (!editRef.current) return
    const serialized = serialize(editRef.current)
    lastSerialized.current = serialized
    onChange(serialized)
  }

  // Insert text/token at cursor position
  function insertAtCursor(token: string) {
    const el = editRef.current
    if (!el) return
    el.focus()
    const sel = window.getSelection()
    if (!sel || sel.rangeCount === 0) return
    const range = sel.getRangeAt(0)
    range.deleteContents()

    // Create the chip element
    const tokens = parseExprTokens(token)
    const frag = document.createDocumentFragment()
    for (const tok of tokens) {
      if (tok.type === "text") {
        frag.appendChild(document.createTextNode(tok.value))
      } else {
        const chip = document.createElement("span")
        chip.contentEditable = "false"
        chip.dataset.token = tok.type === "field" ? `{{${tok.value}}}` : tok.value
        chip.className =
          tok.type === "field"
            ? "inline-flex items-center gap-0.5 rounded bg-primary/15 px-1 py-px mx-0.5 text-[10px] font-semibold text-primary align-baseline select-none cursor-default"
            : "inline-flex items-center gap-0.5 rounded bg-amber-500/15 px-1 py-px mx-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400 align-baseline select-none cursor-default"
        chip.textContent = tok.type === "field" ? tok.value : tok.value
        frag.appendChild(chip)
      }
    }
    // Add trailing space so cursor has somewhere to go
    frag.appendChild(document.createTextNode(" "))
    range.insertNode(frag)
    range.collapse(false)
    sel.removeAllRanges()
    sel.addRange(range)
    handleInput()
  }

  // Handle keyboard: Backspace should delete entire chip if cursor is right after it
  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Backspace") {
      const sel = window.getSelection()
      if (!sel || sel.rangeCount === 0 || !sel.isCollapsed) return
      const range = sel.getRangeAt(0)
      const node = range.startContainer
      const offset = range.startOffset
      // If cursor is in text node at position 0, check previous sibling
      if (node.nodeType === Node.TEXT_NODE && offset === 0) {
        const prev = node.previousSibling
        if (prev instanceof HTMLElement && prev.dataset.token) {
          e.preventDefault()
          prev.remove()
          handleInput()
        }
      }
      // If cursor is in the container element
      if (node === editRef.current && offset > 0) {
        const child = node.childNodes[offset - 1]
        if (child instanceof HTMLElement && child.dataset.token) {
          e.preventDefault()
          child.remove()
          handleInput()
        }
      }
    }
  }

  // Drag-and-drop field from schema sidebar into expression
  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    e.stopPropagation()
    setIsDragOverExpr(false)
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) {
      insertAtCursor(`{{${field}}}`)
    }
  }

  return (
    <div className="space-y-1.5">
      {/* Editable area */}
      <div
        ref={handleRef}
        contentEditable
        suppressContentEditableWarning
        onInput={handleInput}
        onKeyDown={handleKeyDown}
        onDragOver={(e) => {
          if (e.dataTransfer.types.includes("application/x-shift-field")) {
            e.preventDefault()
            e.dataTransfer.dropEffect = "copy"
            setIsDragOverExpr(true)
          }
        }}
        onDragLeave={() => setIsDragOverExpr(false)}
        onDrop={handleDrop}
        data-placeholder="Arraste campos ou digite expressão..."
        className={cn(
          "min-h-[60px] w-full rounded-md border bg-background px-2.5 py-2 text-xs text-foreground outline-none transition-colors",
          "focus:ring-1 focus:ring-primary",
          "empty:before:content-[attr(data-placeholder)] empty:before:text-muted-foreground/60",
          isDragOverExpr ? "border-primary bg-primary/5" : "border-input",
        )}
        style={{ lineHeight: "1.7", whiteSpace: "pre-wrap", wordBreak: "break-word" }}
      />

      {/* Quick-insert bar: fields + system vars */}
      <div className="flex flex-wrap items-center gap-1">
        {upstreamFields.slice(0, 8).map((f, fi) => (
          <button
            key={`${f}-${fi}`}
            type="button"
            onClick={() => insertAtCursor(`{{${f}}}`)}
            className="rounded bg-primary/10 px-1.5 py-px text-[9px] font-medium text-primary/70 transition-colors hover:bg-primary/20 hover:text-primary"
          >
            {f}
          </button>
        ))}
        {upstreamFields.length > 8 && (
          <span className="text-[9px] text-muted-foreground/50">+{upstreamFields.length - 8}</span>
        )}

        <span className="mx-0.5 text-muted-foreground/20">|</span>

        <div className="relative">
          <button
            type="button"
            onClick={() => setShowVars(!showVars)}
            className="rounded bg-amber-500/10 px-1.5 py-px text-[9px] font-medium text-amber-600 dark:text-amber-400 transition-colors hover:bg-amber-500/20"
          >
            Variáveis ▾
          </button>
          {showVars && (
            <div className="absolute left-0 top-full z-20 mt-1 min-w-[140px] rounded-md border border-border bg-popover p-1 shadow-md">
              {SYSTEM_VARS.map((v) => (
                <button
                  key={v.token}
                  type="button"
                  onClick={() => { insertAtCursor(v.token); setShowVars(false) }}
                  className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[10px] transition-colors hover:bg-muted"
                >
                  <span className="font-mono font-semibold text-amber-600 dark:text-amber-400">
                    {v.token}
                  </span>
                  <span className="text-muted-foreground">{v.description}</span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

const CARD_DRAG_TYPE = "application/x-shift-card"
const FIELD_DRAG_TYPE = "application/x-shift-field"

export function MapperConfig({ data, onUpdate }: MapperConfigProps) {
  const upstreamFields = useUpstreamFields()
  const [isDragOver, setIsDragOver]     = useState(false)
  const [collapsed,  setCollapsed]      = useState<Set<string>>(new Set())
  const [draggedIdx, setDraggedIdx]     = useState<number | null>(null)
  const [dragOverIdx, setDragOverIdx]   = useState<number | null>(null)

  const mappings: Mapping[] = Array.isArray(data.mappings)
    ? (data.mappings as Record<string, unknown>[]).map(normalise)
    : []

  const dropUnmapped = Boolean(data.drop_unmapped)

  const setMappings = useCallback(
    (next: Mapping[]) => onUpdate({ ...data, mappings: next }),
    [data, onUpdate],
  )

  // ─── Collapse helpers ─────────────────────────────────────────────────────

  function collapseKey(m: Mapping, i: number): string {
    return m.target || `__idx_${i}`
  }

  function toggleCollapse(m: Mapping, i: number) {
    const key = collapseKey(m, i)
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key)
      else next.add(key)
      return next
    })
  }

  // ─── Card reorder helpers ─────────────────────────────────────────────────

  function handleCardDragStart(e: React.DragEvent, index: number) {
    e.dataTransfer.setData(CARD_DRAG_TYPE, String(index))
    e.dataTransfer.effectAllowed = "move"
    setDraggedIdx(index)
  }

  function handleCardDragEnd() {
    setDraggedIdx(null)
    setDragOverIdx(null)
  }

  function handleCardDragOver(e: React.DragEvent, index: number) {
    if (!e.dataTransfer.types.includes(CARD_DRAG_TYPE)) return
    e.preventDefault()
    setDragOverIdx(index)
  }

  function handleCardDrop(e: React.DragEvent, targetIndex: number) {
    if (!e.dataTransfer.types.includes(CARD_DRAG_TYPE)) return
    e.preventDefault()
    if (draggedIdx === null || draggedIdx === targetIndex) {
      setDraggedIdx(null)
      setDragOverIdx(null)
      return
    }
    const next = [...mappings]
    const [removed] = next.splice(draggedIdx, 1)
    next.splice(targetIndex, 0, removed)
    setMappings(next)
    setDraggedIdx(null)
    setDragOverIdx(null)
  }

  // ─── Mutation helpers ──────────────────────────────────────────────────────

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
    setMappings(
      mappings.map((m, i) =>
        i === index ? recomputeExpression({ ...m, ...patch }) : m,
      ),
    )
  }

  function toggleTransform(index: number, id: string) {
    const m        = mappings[index]
    const current  = m.transforms ?? []
    const isActive = current.some((e) => entryId(e) === id)

    let next: TransformEntry[]
    if (isActive) {
      next = current.filter((e) => entryId(e) !== id)
    } else {
      const tDef = TRANSFORMS.find((t) => t.id === id)
      if (tDef?.hasParams) {
        const defaultParams: Record<string, string> = {}
        for (const pd of tDef.paramDefs ?? []) defaultParams[pd.key] = ""
        next = [...current, { id, params: defaultParams }]
      } else {
        next = [...current, id]
      }
    }
    updateMapping(index, { transforms: next })
  }

  function updateTransformParam(
    mappingIndex: number,
    transformId: string,
    paramKey: string,
    value: string,
  ) {
    const m          = mappings[mappingIndex]
    const transforms = (m.transforms ?? []).map((entry) => {
      if (typeof entry !== "string" && entry.id === transformId) {
        return { ...entry, params: { ...entry.params, [paramKey]: value } }
      }
      return entry
    })
    updateMapping(mappingIndex, { transforms })
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

  // ─── Drag & Drop (field from sidebar) ─────────────────────────────────────

  function getField(e: React.DragEvent) {
    return e.dataTransfer.getData(FIELD_DRAG_TYPE)
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
    const field = getField(e)
    if (!field) return          // not a field drag — let event bubble for card reorder
    e.stopPropagation()
    const m          = mappings[index]
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
          <div className="flex items-center gap-2">
            {mappings.length > 0 && (
              <button
                type="button"
                onClick={() => {
                  const allCollapsed = mappings.every((m, i) => collapsed.has(collapseKey(m, i)))
                  if (allCollapsed) {
                    setCollapsed(new Set())
                  } else {
                    setCollapsed(new Set(mappings.map((m, i) => collapseKey(m, i))))
                  }
                }}
                className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground"
              >
                {mappings.every((m, i) => collapsed.has(collapseKey(m, i)))
                  ? <><ChevronsUpDown className="size-3" /> Expandir todos</>
                  : <><ChevronsDownUp className="size-3" /> Minimizar todos</>
                }
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
            const isCollapsed   = collapsed.has(collapseKey(m, i))
            const isDragged     = draggedIdx === i
            const isDragTarget  = dragOverIdx === i && draggedIdx !== null && draggedIdx !== i
            const activeLabels  = (m.transforms ?? [])
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

                  {/* Drag handle */}
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

                  {/* Collapse toggle */}
                  <button
                    type="button"
                    onClick={() => toggleCollapse(m, i)}
                    title={isCollapsed ? "Expandir" : "Minimizar"}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground/50 transition-colors hover:bg-muted hover:text-foreground"
                  >
                    <ChevronDown
                      className={cn(
                        "size-3.5 transition-transform duration-150",
                        isCollapsed && "-rotate-90",
                      )}
                    />
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
                          <span
                            key={label}
                            className="rounded-full bg-primary/10 px-1.5 py-px text-[9px] font-medium text-primary/70"
                          >
                            {label}
                          </span>
                        ))}
                      </>
                    )}
                  </div>
                )}

                {/* ── Expanded content ── */}
                {!isCollapsed && (
                  <div className="space-y-2 px-2.5 pb-2.5">

                    {/* ── Row 2: value type toggle + value input ── */}
                    <div
                      className="flex items-center gap-1.5"
                      onDragOver={(e) => {
                        if (!e.dataTransfer.types.includes(FIELD_DRAG_TYPE)) return
                        e.preventDefault()
                        e.dataTransfer.dropEffect = "copy"
                      }}
                      onDrop={(e) => handleDropOnValue(e, i)}
                    >
                      {/* Toggle: field → static → expression → field */}
                      <button
                        type="button"
                        title={
                          m.valueType === "field"    ? "Campo · Clique para valor fixo" :
                          m.valueType === "static"   ? "Valor fixo · Clique para expressão" :
                                                       "Expressão · Clique para campo"
                        }
                        onClick={() => {
                          const next: ValueType =
                            m.valueType === "field"  ? "static" :
                            m.valueType === "static" ? "expression" : "field"
                          updateMapping(i, {
                            valueType: next,
                            source: "",
                            value: "",
                            exprTemplate: "",
                            transforms: [],
                          })
                        }}
                        className={cn(
                          "flex size-7 shrink-0 items-center justify-center rounded-md border transition-colors",
                          m.valueType === "field"
                            ? "border-primary/40 bg-primary/10 text-primary"
                            : m.valueType === "expression"
                              ? "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400"
                              : "border-border bg-background text-muted-foreground hover:text-foreground",
                        )}
                      >
                        {m.valueType === "field"
                          ? <Link2 className="size-3.5" />
                          : m.valueType === "expression"
                            ? <Braces className="size-3.5" />
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
                            {upstreamFields.map((f, fi) => (
                              <option
                                key={`${f}-${fi}`}
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
                      ) : m.valueType === "static" ? (
                        <input
                          type="text"
                          value={m.value ?? ""}
                          onChange={(e) => updateMapping(i, { value: e.target.value })}
                          placeholder="valor fixo..."
                          className="h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                        />
                      ) : (
                        <span className="text-[10px] text-amber-600 dark:text-amber-400 font-medium">Expressão</span>
                      )}
                    </div>

                    {/* ── Expression editor (expression mode only) ── */}
                    {m.valueType === "expression" && (
                      <ExpressionInput
                        value={m.exprTemplate ?? ""}
                        onChange={(v) => updateMapping(i, { exprTemplate: v })}
                        upstreamFields={upstreamFields}
                      />
                    )}

                    {/* ── Row 3: transform chips + param inputs (field mode only) ── */}
                    {m.valueType === "field" && m.source && (
                      <div className="space-y-1.5 pt-0.5">

                        {/* Chips */}
                        <div className="flex flex-wrap gap-1">
                          {TRANSFORMS.map((t) => {
                            const active = (m.transforms ?? []).some((e) => entryId(e) === t.id)
                            return (
                              <button
                                key={t.id}
                                type="button"
                                title={t.description}
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

                        {/* Param inputs for active parametrized transforms */}
                        {(m.transforms ?? [])
                          .filter((e): e is ParamTransformEntry => typeof e !== "string")
                          .map((entry) => {
                            const tDef = TRANSFORMS.find((t) => t.id === entry.id)
                            if (!tDef?.paramDefs?.length) return null
                            return (
                              <div
                                key={entry.id}
                                className="rounded-md border border-primary/20 bg-primary/5 px-2.5 py-2 space-y-1.5"
                              >
                                <span className="text-[10px] font-semibold text-primary">
                                  {tDef.label}
                                </span>
                                <div className="flex flex-wrap gap-x-3 gap-y-1.5">
                                  {tDef.paramDefs.map((pd) => (
                                    <div key={pd.key} className="flex min-w-0 flex-1 items-center gap-1.5">
                                      <span className="shrink-0 text-[10px] text-muted-foreground">
                                        {pd.label}:
                                      </span>
                                      <input
                                        type="text"
                                        value={entry.params[pd.key] ?? ""}
                                        onChange={(e) =>
                                          updateTransformParam(i, entry.id, pd.key, e.target.value)
                                        }
                                        placeholder={pd.placeholder}
                                        className="h-5 min-w-0 flex-1 rounded border border-input bg-background px-1.5 text-[10px] text-foreground outline-none placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"
                                      />
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )
                          })}
                      </div>
                    )}
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
