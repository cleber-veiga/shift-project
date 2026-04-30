"use client"

import { useEffect, useRef, useState } from "react"
import { createPortal } from "react-dom"
import {
  Calculator,
  ChevronDown,
  ChevronsDownUp,
  ChevronsUpDown,
  Code2,
  GitBranch,
  Hash,
  Link2,
  Plus,
  Quote,
  Sparkles,
  Trash2,
  Type,
  X,
} from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import { ExpressionEditor } from "@/components/workflow/value-input"

// ════════════════════════════════════════════════════════════════════════════
// Tipos
// ════════════════════════════════════════════════════════════════════════════

type Mode = "calc" | "cond" | "text" | "advanced"

type OperandKind = "field" | "number" | "text"

interface Operand {
  kind: OperandKind
  value: string
}

interface CalcState {
  operands: Operand[]
  operators: string[] // length = operands.length - 1
  wrapper: WrapperFn
}

type WrapperFn =
  | "none"
  | "round2"
  | "round0"
  | "abs"
  | "coalesce0"
  | "ceil"
  | "floor"
  | "sqrt"

interface CondBranch {
  left: Operand
  op: string // ">", "<", "=", "!=", ">=", "<=", "is_null", "is_not_null"
  right: Operand
  then: Operand
}

interface CondState {
  branches: CondBranch[]
  fallback: Operand
}

type TextTransformId =
  | "upper"
  | "lower"
  | "trim"
  | "left"
  | "right"
  | "concat"

interface TextTransform {
  id: TextTransformId
  params?: Record<string, string>
}

interface TextState {
  source: string // column name
  transforms: TextTransform[]
}

interface MathExpression {
  target_column: string
  expression: string // SQL — única coisa que o backend lê
  // Estado da UI (ignorado pelo backend; sobrevive no JSON do workflow):
  _mode?: Mode
  _calc?: CalcState
  _cond?: CondState
  _text?: TextState
  _advanced?: string // template do ExpressionEditor (com `{{coluna}}`)
}

interface MathConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ════════════════════════════════════════════════════════════════════════════
// Helpers SQL
// ════════════════════════════════════════════════════════════════════════════

function escapeSqlString(s: string): string {
  return s.replace(/'/g, "''")
}

function quoteCol(name: string): string {
  return `"${name}"`
}

function operandToSql(op: Operand | undefined): string {
  if (!op) return "NULL"
  if (op.kind === "field") return op.value ? quoteCol(op.value) : "NULL"
  if (op.kind === "number") return op.value.trim() || "0"
  // text literal
  return `'${escapeSqlString(op.value)}'`
}

function wrapWith(inner: string, wrapper: WrapperFn): string {
  if (!inner) return ""
  switch (wrapper) {
    case "round2":     return `ROUND(${inner}, 2)`
    case "round0":     return `ROUND(${inner})`
    case "abs":        return `ABS(${inner})`
    case "coalesce0":  return `COALESCE(${inner}, 0)`
    case "ceil":       return `CEIL(${inner})`
    case "floor":      return `FLOOR(${inner})`
    case "sqrt":       return `SQRT(${inner})`
    default:           return inner
  }
}

function compileCalc(state: CalcState): string {
  if (!state.operands.length) return ""
  const parts: string[] = [operandToSql(state.operands[0])]
  for (let i = 1; i < state.operands.length; i++) {
    parts.push(state.operators[i - 1] || "+")
    parts.push(operandToSql(state.operands[i]))
  }
  return wrapWith(parts.join(" "), state.wrapper)
}

function compileCond(state: CondState): string {
  if (!state.branches.length) return ""
  const parts: string[] = ["CASE"]
  for (const b of state.branches) {
    let cond: string
    if (b.op === "is_null") cond = `${operandToSql(b.left)} IS NULL`
    else if (b.op === "is_not_null") cond = `${operandToSql(b.left)} IS NOT NULL`
    else cond = `${operandToSql(b.left)} ${b.op} ${operandToSql(b.right)}`
    parts.push(`WHEN ${cond} THEN ${operandToSql(b.then)}`)
  }
  parts.push(`ELSE ${operandToSql(state.fallback)}`)
  parts.push("END")
  return parts.join(" ")
}

function compileText(state: TextState): string {
  if (!state.source) return ""
  let expr = quoteCol(state.source)
  for (const t of state.transforms) {
    switch (t.id) {
      case "upper": expr = `UPPER(${expr})`; break
      case "lower": expr = `LOWER(${expr})`; break
      case "trim":  expr = `TRIM(${expr})`; break
      case "left": {
        const n = parseInt(t.params?.n ?? "0", 10) || 0
        expr = `LEFT(${expr}, ${n})`
        break
      }
      case "right": {
        const n = parseInt(t.params?.n ?? "0", 10) || 0
        expr = `RIGHT(${expr}, ${n})`
        break
      }
      case "concat": {
        const sep = escapeSqlString(t.params?.sep ?? "")
        const otherCol = t.params?.other ?? ""
        const otherSql = otherCol ? quoteCol(otherCol) : `''`
        expr = sep
          ? `CONCAT(${expr}, '${sep}', ${otherSql})`
          : `CONCAT(${expr}, ${otherSql})`
        break
      }
    }
  }
  return expr
}

function templateToSql(template: string): string {
  return template
    .replace(/\{\{([^}]+)\}\}/g, (_, name) => quoteCol(String(name).trim()))
    .replace(/\$now\b/g, "CURRENT_TIMESTAMP")
    .replace(/\$today\b/g, "CURRENT_DATE")
}

function sqlToTemplate(sql: string, upstreamFields: string[]): string {
  if (!sql) return ""
  let result = sql
  for (const f of upstreamFields) {
    const escaped = f.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    result = result.replace(new RegExp(`"${escaped}"`, "g"), `{{${f}}}`)
  }
  return result
    .replace(/\bCURRENT_TIMESTAMP\b/g, "$now")
    .replace(/\bCURRENT_DATE\b/g, "$today")
}

// ════════════════════════════════════════════════════════════════════════════
// Detecção de modo no load — best-effort baseado em padrões simples no SQL.
// Se nenhum modo estruturado bate, abrimos em "Avançado" (sempre seguro).
// ════════════════════════════════════════════════════════════════════════════

function detectMode(exp: MathExpression): Mode {
  if (exp._mode) return exp._mode
  const sql = (exp.expression || "").trim()
  if (!sql) return "calc"
  if (/^\s*CASE\s+WHEN/i.test(sql)) return "cond"
  if (/^\s*(UPPER|LOWER|TRIM|LEFT|RIGHT|CONCAT)\s*\(/i.test(sql)) return "text"
  return "advanced"
}

// ════════════════════════════════════════════════════════════════════════════
// OperandInput — entrada que aceita campo (chip), número ou texto literal.
// Usado em Cálculo e Condição.
// ════════════════════════════════════════════════════════════════════════════

const KIND_META: Record<OperandKind, { icon: typeof Hash; tooltip: string }> = {
  field:  { icon: Link2, tooltip: "Coluna" },
  number: { icon: Hash,  tooltip: "Número" },
  text:   { icon: Quote, tooltip: "Texto" },
}

function OperandInput({
  operand,
  onChange,
  allowedKinds,
  upstreamFields,
  placeholder,
  compact = false,
}: {
  operand: Operand
  onChange: (next: Operand) => void
  allowedKinds: OperandKind[]
  upstreamFields: string[]
  placeholder?: string
  compact?: boolean
}) {
  function changeKind(next: OperandKind) {
    onChange({ kind: next, value: "" })
  }
  function changeValue(value: string) {
    onChange({ ...operand, value })
  }

  function handleDragOver(e: React.DragEvent) {
    if (e.dataTransfer.types.includes("application/x-shift-field")) {
      e.preventDefault()
      e.dataTransfer.dropEffect = "copy"
    }
  }
  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    const f = e.dataTransfer.getData("application/x-shift-field")
    if (f) onChange({ kind: "field", value: f })
  }

  const KindIcon = KIND_META[operand.kind].icon
  const baseInputClass =
    "h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"

  // Renderiza o seletor de tipo só quando há mais de uma opção
  const showKindToggle = allowedKinds.length > 1
  const kindToggle = showKindToggle ? (
    <div className="flex shrink-0 overflow-hidden rounded-md border border-input">
      {allowedKinds.map((k) => {
        const Icon = KIND_META[k].icon
        const active = operand.kind === k
        return (
          <button
            key={k}
            type="button"
            onClick={() => changeKind(k)}
            title={KIND_META[k].tooltip}
            className={cn(
              "flex h-7 w-7 items-center justify-center transition-colors",
              active
                ? "bg-primary/10 text-primary"
                : "bg-background text-muted-foreground hover:bg-muted",
            )}
          >
            <Icon className="size-3.5" />
          </button>
        )
      })}
    </div>
  ) : null

  const valueInput = (() => {
    if (operand.kind === "field") {
      // Modo chip: se valor existe → chip violeta clicável; senão → dropdown
      if (operand.value) {
        return (
          <div
            className="flex min-w-0 flex-1 items-center gap-1.5"
            onDragOver={handleDragOver}
            onDrop={handleDrop}
          >
            {!showKindToggle && (
              <span
                className="flex size-7 shrink-0 items-center justify-center rounded-md border border-primary/40 bg-primary/10 text-primary"
                title="Campo linkado"
              >
                <Link2 className="size-3.5" />
              </span>
            )}
            <button
              type="button"
              onClick={() => changeValue("")}
              className="inline-flex h-7 min-w-0 items-center rounded-md bg-primary/12 px-2 text-[11px] font-semibold text-primary transition-colors hover:bg-primary/20"
              title="Clique para alterar"
            >
              <span className="truncate">{operand.value}</span>
            </button>
          </div>
        )
      }
      // Sem valor: dropdown de campos disponíveis
      if (upstreamFields.length === 0) {
        return (
          <input
            type="text"
            value={operand.value}
            onChange={(e) => changeValue(e.target.value)}
            onDragOver={handleDragOver}
            onDrop={handleDrop}
            placeholder={placeholder ?? "nome da coluna"}
            className={baseInputClass}
          />
        )
      }
      return (
        <select
          autoFocus={!operand.value}
          value={operand.value}
          onChange={(e) => changeValue(e.target.value)}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          className={baseInputClass}
        >
          <option value="">-- coluna --</option>
          {upstreamFields.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      )
    }
    if (operand.kind === "number") {
      return (
        <input
          type="number"
          value={operand.value}
          onChange={(e) => changeValue(e.target.value)}
          placeholder="0"
          step="any"
          className={cn(baseInputClass, "tabular-nums")}
        />
      )
    }
    // text
    return (
      <input
        type="text"
        value={operand.value}
        onChange={(e) => changeValue(e.target.value)}
        placeholder="texto..."
        className={baseInputClass}
      />
    )
  })()

  return (
    <div className={cn("flex min-w-0 items-center gap-1.5", compact && "gap-1")}>
      {kindToggle}
      {valueInput}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Modo CÁLCULO
// ════════════════════════════════════════════════════════════════════════════

const ARITH_OPERATORS: { value: string; label: string }[] = [
  { value: "+", label: "+" },
  { value: "-", label: "−" },
  { value: "*", label: "×" },
  { value: "/", label: "÷" },
  { value: "%", label: "mod" },
]

const WRAPPERS: { id: WrapperFn; label: string; desc: string }[] = [
  { id: "none",      label: "Sem ajuste",         desc: "Não envolve com nenhuma função" },
  { id: "round2",    label: "Arredondar (2 casas)", desc: "ROUND(..., 2)" },
  { id: "round0",    label: "Arredondar (inteiro)", desc: "ROUND(...)" },
  { id: "ceil",      label: "Arredondar p/ cima",   desc: "CEIL(...)" },
  { id: "floor",     label: "Arredondar p/ baixo",  desc: "FLOOR(...)" },
  { id: "abs",       label: "Valor absoluto",       desc: "ABS(...) — sempre positivo" },
  { id: "sqrt",      label: "Raiz quadrada",        desc: "SQRT(...)" },
  { id: "coalesce0", label: "Tratar vazio como 0",  desc: "COALESCE(..., 0)" },
]

function CalcMode({
  state,
  onChange,
  upstreamFields,
}: {
  state: CalcState
  onChange: (next: CalcState) => void
  upstreamFields: string[]
}) {
  function setOperand(i: number, op: Operand) {
    const next = [...state.operands]
    next[i] = op
    onChange({ ...state, operands: next })
  }
  function setOperator(i: number, op: string) {
    const next = [...state.operators]
    next[i] = op
    onChange({ ...state, operators: next })
  }
  function addOperand() {
    onChange({
      ...state,
      operands: [...state.operands, { kind: "field", value: "" }],
      operators: [...state.operators, "+"],
    })
  }
  function removeOperand(i: number) {
    if (state.operands.length <= 1) return
    const operands = state.operands.filter((_, idx) => idx !== i)
    // Remove operador correspondente: se removemos o primeiro operando, sobra
    // o operador da posição 0; senão, sobra o operador anterior (i - 1).
    const operators = i === 0
      ? state.operators.slice(1)
      : state.operators.filter((_, idx) => idx !== i - 1)
    onChange({ ...state, operands, operators })
  }

  function handleDropZone(e: React.DragEvent) {
    e.preventDefault()
    const f = e.dataTransfer.getData("application/x-shift-field")
    if (f) {
      onChange({
        ...state,
        operands: [...state.operands, { kind: "field", value: f }],
        operators: [...state.operators, "+"],
      })
    }
  }

  return (
    <div className="space-y-2">
      <div className="space-y-1.5">
        {state.operands.map((op, i) => (
          <div key={i} className="flex items-center gap-1.5">
            {/* Operador (exceto antes do primeiro operando) */}
            {i > 0 ? (
              <select
                value={state.operators[i - 1] ?? "+"}
                onChange={(e) => setOperator(i - 1, e.target.value)}
                className="h-7 w-12 shrink-0 rounded-md border border-input bg-background text-center text-xs font-bold text-foreground outline-none focus:ring-1 focus:ring-primary"
              >
                {ARITH_OPERATORS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            ) : (
              <span className="flex h-7 w-12 shrink-0 items-center justify-center text-[10px] font-medium text-muted-foreground/50">
                =
              </span>
            )}
            <div className="min-w-0 flex-1">
              <OperandInput
                operand={op}
                onChange={(next) => setOperand(i, next)}
                allowedKinds={["field", "number"]}
                upstreamFields={upstreamFields}
              />
            </div>
            <button
              type="button"
              onClick={() => removeOperand(i)}
              disabled={state.operands.length <= 1}
              className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive disabled:pointer-events-none disabled:opacity-30"
              aria-label="Remover termo"
            >
              <X className="size-3" />
            </button>
          </div>
        ))}
      </div>

      {/* Zona de drop / botão adicionar */}
      <div
        onDragOver={(e) => {
          if (!e.dataTransfer.types.includes("application/x-shift-field")) return
          e.preventDefault()
          e.dataTransfer.dropEffect = "copy"
        }}
        onDrop={handleDropZone}
        onClick={addOperand}
        className="flex w-full cursor-pointer items-center justify-center gap-1 rounded-md border border-dashed border-border py-1.5 text-[10px] font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
      >
        <Plus className="size-3" />
        Adicionar termo
      </div>

      {/* Wrapper opcional */}
      <div className="flex items-center gap-2 pt-1">
        <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted-foreground/70">
          Envolver com
        </span>
        <select
          value={state.wrapper}
          onChange={(e) => onChange({ ...state, wrapper: e.target.value as WrapperFn })}
          className="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
        >
          {WRAPPERS.map((w) => (
            <option key={w.id} value={w.id} title={w.desc}>
              {w.label}
            </option>
          ))}
        </select>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Modo CONDIÇÃO
// ════════════════════════════════════════════════════════════════════════════

const COND_OPERATORS: { value: string; label: string; needsRight: boolean }[] = [
  { value: "=",            label: "igual a",         needsRight: true  },
  { value: "!=",           label: "diferente de",    needsRight: true  },
  { value: ">",            label: "maior que",       needsRight: true  },
  { value: ">=",           label: "maior ou igual",  needsRight: true  },
  { value: "<",            label: "menor que",       needsRight: true  },
  { value: "<=",           label: "menor ou igual",  needsRight: true  },
  { value: "is_null",      label: "está vazio",      needsRight: false },
  { value: "is_not_null",  label: "não está vazio",  needsRight: false },
]

function CondMode({
  state,
  onChange,
  upstreamFields,
}: {
  state: CondState
  onChange: (next: CondState) => void
  upstreamFields: string[]
}) {
  function setBranch(i: number, patch: Partial<CondBranch>) {
    const next = state.branches.map((b, idx) => (idx === i ? { ...b, ...patch } : b))
    onChange({ ...state, branches: next })
  }
  function addBranch() {
    onChange({
      ...state,
      branches: [
        ...state.branches,
        {
          left: { kind: "field", value: "" },
          op: ">",
          right: { kind: "number", value: "0" },
          then: { kind: "text", value: "" },
        },
      ],
    })
  }
  function removeBranch(i: number) {
    if (state.branches.length <= 1) return
    onChange({ ...state, branches: state.branches.filter((_, idx) => idx !== i) })
  }
  function setFallback(op: Operand) {
    onChange({ ...state, fallback: op })
  }

  return (
    <div className="space-y-2">
      {state.branches.map((b, i) => {
        const opMeta = COND_OPERATORS.find((o) => o.value === b.op)
        return (
          <div
            key={i}
            className="rounded-md border border-border bg-background/40 p-2"
          >
            <div className="mb-1.5 flex items-center justify-between">
              <span className="text-[10px] font-bold uppercase tracking-wider text-primary/80">
                {i === 0 ? "Se" : "Senão se"}
              </span>
              {state.branches.length > 1 && (
                <button
                  type="button"
                  onClick={() => removeBranch(i)}
                  className="flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  aria-label="Remover condição"
                >
                  <X className="size-3" />
                </button>
              )}
            </div>
            <div className="space-y-1.5">
              <OperandInput
                operand={b.left}
                onChange={(next) => setBranch(i, { left: next })}
                allowedKinds={["field", "number", "text"]}
                upstreamFields={upstreamFields}
              />
              <select
                value={b.op}
                onChange={(e) => setBranch(i, { op: e.target.value })}
                className="h-7 w-full rounded-md border border-input bg-background px-2 text-xs font-medium text-foreground outline-none focus:ring-1 focus:ring-primary"
              >
                {COND_OPERATORS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
              {opMeta?.needsRight && (
                <OperandInput
                  operand={b.right}
                  onChange={(next) => setBranch(i, { right: next })}
                  allowedKinds={["field", "number", "text"]}
                  upstreamFields={upstreamFields}
                />
              )}
              <div className="flex items-center gap-2 border-t border-border/50 pt-1.5">
                <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400">
                  Então
                </span>
                <div className="min-w-0 flex-1">
                  <OperandInput
                    operand={b.then}
                    onChange={(next) => setBranch(i, { then: next })}
                    allowedKinds={["field", "number", "text"]}
                    upstreamFields={upstreamFields}
                  />
                </div>
              </div>
            </div>
          </div>
        )
      })}

      <button
        type="button"
        onClick={addBranch}
        className="flex w-full items-center justify-center gap-1 rounded-md border border-dashed border-border py-1.5 text-[10px] font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
      >
        <Plus className="size-3" />
        Adicionar Senão se
      </button>

      <div className="flex items-center gap-2 rounded-md border border-border bg-background/40 p-2">
        <span className="shrink-0 text-[10px] font-bold uppercase tracking-wider text-amber-600 dark:text-amber-400">
          Senão
        </span>
        <div className="min-w-0 flex-1">
          <OperandInput
            operand={state.fallback}
            onChange={setFallback}
            allowedKinds={["field", "number", "text"]}
            upstreamFields={upstreamFields}
          />
        </div>
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Modo TEXTO
// ════════════════════════════════════════════════════════════════════════════

const TEXT_TRANSFORMS: {
  id: TextTransformId
  label: string
  desc: string
  paramKey?: string
  paramLabel?: string
  paramPlaceholder?: string
  paramKey2?: string
  paramLabel2?: string
}[] = [
  { id: "upper",  label: "MAIÚSCULAS",      desc: "Converter para maiúsculas" },
  { id: "lower",  label: "minúsculas",      desc: "Converter para minúsculas" },
  { id: "trim",   label: "Remover espaços", desc: "Remove espaços do início e fim" },
  { id: "left",   label: "Primeiros N caracteres", desc: "Mantém os N primeiros caracteres", paramKey: "n", paramLabel: "Quantidade", paramPlaceholder: "ex: 3" },
  { id: "right",  label: "Últimos N caracteres",   desc: "Mantém os N últimos caracteres",   paramKey: "n", paramLabel: "Quantidade", paramPlaceholder: "ex: 4" },
  { id: "concat", label: "Juntar com outra coluna", desc: "Concatena com outra coluna (com separador opcional)", paramKey: "other", paramLabel: "Outra coluna", paramKey2: "sep", paramLabel2: "Separador" },
]

function TextMode({
  state,
  onChange,
  upstreamFields,
}: {
  state: TextState
  onChange: (next: TextState) => void
  upstreamFields: string[]
}) {
  function setSource(value: string) {
    onChange({ ...state, source: value })
  }
  function addTransform(id: TextTransformId) {
    const meta = TEXT_TRANSFORMS.find((t) => t.id === id)!
    const params: Record<string, string> = {}
    if (meta.paramKey) params[meta.paramKey] = ""
    if (meta.paramKey2) params[meta.paramKey2] = ""
    onChange({
      ...state,
      transforms: [...state.transforms, { id, params }],
    })
  }
  function removeTransform(i: number) {
    onChange({
      ...state,
      transforms: state.transforms.filter((_, idx) => idx !== i),
    })
  }
  function updateTransformParam(i: number, key: string, value: string) {
    onChange({
      ...state,
      transforms: state.transforms.map((t, idx) =>
        idx === i ? { ...t, params: { ...(t.params ?? {}), [key]: value } } : t,
      ),
    })
  }

  const [pickerOpen, setPickerOpen] = useState(false)

  function handleDropSource(e: React.DragEvent) {
    e.preventDefault()
    const f = e.dataTransfer.getData("application/x-shift-field")
    if (f) setSource(f)
  }

  return (
    <div className="space-y-2">
      {/* Fonte */}
      <div className="flex items-center gap-2">
        <span className="shrink-0 text-[10px] uppercase tracking-wider text-muted-foreground/70">
          Coluna
        </span>
        <div className="min-w-0 flex-1">
          <OperandInput
            operand={{ kind: "field", value: state.source }}
            onChange={(op) => setSource(op.value)}
            allowedKinds={["field"]}
            upstreamFields={upstreamFields}
          />
        </div>
      </div>

      {/* Cadeia de transforms */}
      {state.transforms.length > 0 && (
        <div className="space-y-1">
          {state.transforms.map((t, i) => {
            const meta = TEXT_TRANSFORMS.find((m) => m.id === t.id)!
            return (
              <div
                key={i}
                className="rounded-md border border-border bg-background/40 p-2"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium text-foreground">
                    <span className="mr-1.5 text-[9px] font-bold text-muted-foreground/50">
                      {i + 1}.
                    </span>
                    {meta.label}
                  </span>
                  <button
                    type="button"
                    onClick={() => removeTransform(i)}
                    className="flex size-6 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    aria-label="Remover transformação"
                  >
                    <X className="size-3" />
                  </button>
                </div>
                {meta.paramKey && (
                  <div className="mt-1.5 grid grid-cols-2 gap-1.5">
                    <label className="flex items-center gap-1.5">
                      <span className="shrink-0 text-[10px] text-muted-foreground/70">
                        {meta.paramLabel}
                      </span>
                      {meta.paramKey === "other" ? (
                        <select
                          value={t.params?.[meta.paramKey] ?? ""}
                          onChange={(e) =>
                            updateTransformParam(i, meta.paramKey!, e.target.value)
                          }
                          className="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-1.5 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
                        >
                          <option value="">-- coluna --</option>
                          {upstreamFields.map((f) => (
                            <option key={f} value={f}>
                              {f}
                            </option>
                          ))}
                        </select>
                      ) : (
                        <input
                          type="text"
                          value={t.params?.[meta.paramKey] ?? ""}
                          onChange={(e) =>
                            updateTransformParam(i, meta.paramKey!, e.target.value)
                          }
                          placeholder={meta.paramPlaceholder ?? ""}
                          className="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-1.5 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
                        />
                      )}
                    </label>
                    {meta.paramKey2 && (
                      <label className="flex items-center gap-1.5">
                        <span className="shrink-0 text-[10px] text-muted-foreground/70">
                          {meta.paramLabel2}
                        </span>
                        <input
                          type="text"
                          value={t.params?.[meta.paramKey2] ?? ""}
                          onChange={(e) =>
                            updateTransformParam(i, meta.paramKey2!, e.target.value)
                          }
                          placeholder="ex: ' '"
                          className="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-1.5 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
                        />
                      </label>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Picker de transforms */}
      <div className="relative">
        <button
          type="button"
          onClick={() => setPickerOpen((v) => !v)}
          className="flex w-full items-center justify-center gap-1 rounded-md border border-dashed border-border py-1.5 text-[10px] font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
        >
          <Plus className="size-3" />
          Adicionar transformação
        </button>
        {pickerOpen && (
          <>
            <div className="fixed inset-0 z-10" onClick={() => setPickerOpen(false)} />
            <div className="absolute left-0 right-0 top-full z-20 mt-1 max-h-64 overflow-y-auto rounded-md border border-border bg-popover p-1 shadow-lg">
              {TEXT_TRANSFORMS.map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => {
                    addTransform(t.id)
                    setPickerOpen(false)
                  }}
                  className="flex w-full flex-col rounded px-2 py-1 text-left transition-colors hover:bg-primary/10"
                >
                  <span className="text-[11px] font-medium text-foreground">
                    {t.label}
                  </span>
                  <span className="text-[9px] text-muted-foreground/70">
                    {t.desc}
                  </span>
                </button>
              ))}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Modo AVANÇADO (SQL livre com ExpressionEditor + popover de funções)
// ════════════════════════════════════════════════════════════════════════════

interface FuncSnippet {
  label: string
  sql: string
  snippet: string
  desc: string
  group: "math" | "logic" | "text" | "type"
}

const FUNCTION_SNIPPETS: FuncSnippet[] = [
  { label: "Arredondar",          sql: "ROUND",    snippet: "ROUND(___, 2)",                       desc: "Arredondar para 2 casas decimais",                  group: "math"  },
  { label: "Valor absoluto",      sql: "ABS",      snippet: "ABS(___)",                            desc: "Resultado sempre positivo",                          group: "math"  },
  { label: "Elevar ao quadrado",  sql: "POWER",    snippet: "POWER(___, 2)",                       desc: "Calcula a potência",                                 group: "math"  },
  { label: "Raiz quadrada",       sql: "SQRT",     snippet: "SQRT(___)",                           desc: "Raiz quadrada do número",                            group: "math"  },
  { label: "Arredondar p/ cima",  sql: "CEIL",     snippet: "CEIL(___)",                           desc: "Sempre sobe (1.1 → 2)",                              group: "math"  },
  { label: "Arredondar p/ baixo", sql: "FLOOR",    snippet: "FLOOR(___)",                          desc: "Sempre desce (1.9 → 1)",                             group: "math"  },
  { label: "Se vazio, usar...",   sql: "COALESCE", snippet: "COALESCE(___, 0)",                    desc: "Substitui NULL por outro valor",                     group: "logic" },
  { label: "Se… então… senão…",   sql: "CASE",     snippet: "CASE WHEN ___ THEN ___ ELSE ___ END", desc: "Lógica condicional",                                 group: "logic" },
  { label: "Vira vazio quando…",  sql: "NULLIF",   snippet: "NULLIF(___, 0)",                      desc: "Útil para evitar divisão por zero",                  group: "logic" },
  { label: "MAIÚSCULAS",          sql: "UPPER",    snippet: "UPPER(___)",                          desc: "Texto em maiúsculas",                                group: "text"  },
  { label: "minúsculas",          sql: "LOWER",    snippet: "LOWER(___)",                          desc: "Texto em minúsculas",                                group: "text"  },
  { label: "Remover espaços",     sql: "TRIM",     snippet: "TRIM(___)",                           desc: "Tira espaços do começo e fim",                       group: "text"  },
  { label: "Juntar textos",       sql: "CONCAT",   snippet: "CONCAT(___, ' ', ___)",               desc: "Une dois textos com espaço",                         group: "text"  },
  { label: "Tamanho do texto",    sql: "LENGTH",   snippet: "LENGTH(___)",                         desc: "Conta caracteres",                                   group: "text"  },
  { label: "Converter p/ número", sql: "CAST",     snippet: "CAST(___ AS DECIMAL)",                desc: "Converte para decimal",                              group: "type"  },
  { label: "Converter p/ texto",  sql: "CAST",     snippet: "CAST(___ AS VARCHAR)",                desc: "Converte para texto",                                group: "type"  },
  { label: "Converter p/ data",   sql: "CAST",     snippet: "CAST(___ AS DATE)",                   desc: "Converte texto YYYY-MM-DD para data",                group: "type"  },
]

const GROUP_LABELS: Record<FuncSnippet["group"], string> = {
  math:  "Cálculos",
  logic: "Lógica e valores vazios",
  text:  "Texto",
  type:  "Conversão de tipo",
}

function FunctionsMenu({ onInsert }: { onInsert: (snippet: string) => void }) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef<HTMLButtonElement>(null)
  const [pos, setPos] = useState<{ top: number; left: number; maxH: number } | null>(null)
  const groups = ["math", "logic", "text", "type"] as const

  useEffect(() => {
    if (!open) {
      setPos(null)
      return
    }
    const POPOVER_W = 288
    const MARGIN = 12
    const HARD_CAP = 420
    const update = () => {
      const btn = btnRef.current
      if (!btn) return
      const r = btn.getBoundingClientRect()
      let left = r.right - POPOVER_W
      if (left < 8) left = 8
      const maxLeft = window.innerWidth - POPOVER_W - 8
      if (left > maxLeft) left = maxLeft
      const top = r.bottom + 4
      const maxH = Math.max(180, Math.min(HARD_CAP, window.innerHeight - top - MARGIN))
      setPos({ top, left, maxH })
    }
    update()
    window.addEventListener("scroll", update, true)
    window.addEventListener("resize", update)
    return () => {
      window.removeEventListener("scroll", update, true)
      window.removeEventListener("resize", update)
    }
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false)
    }
    window.addEventListener("keydown", onKey)
    return () => window.removeEventListener("keydown", onKey)
  }, [open])

  const popover =
    open && pos && typeof document !== "undefined"
      ? createPortal(
          <>
            <div className="fixed inset-0 z-[200]" onClick={() => setOpen(false)} />
            <div
              role="menu"
              className="fixed z-[201] flex w-72 flex-col overflow-hidden rounded-lg border border-border bg-popover shadow-xl"
              style={{ top: pos.top, left: pos.left, maxHeight: pos.maxH }}
              onClick={(e) => e.stopPropagation()}
            >
              <p className="shrink-0 border-b border-border bg-muted/30 px-3 py-2 text-[10px] leading-relaxed text-muted-foreground/80">
                Clique em uma função pra inserir. Depois, substitua os{" "}
                <code className="rounded bg-background px-0.5 font-mono font-semibold text-foreground/80">
                  ___
                </code>{" "}
                pelo campo desejado.
              </p>
              <div className="min-h-0 flex-1 overflow-y-auto p-2">
                {groups.map((g) => (
                  <div key={g} className="mb-2 last:mb-0">
                    <p className="mb-1 px-1 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                      {GROUP_LABELS[g]}
                    </p>
                    <div className="space-y-1">
                      {FUNCTION_SNIPPETS.filter((f) => f.group === g).map((f, i) => (
                        <button
                          key={`${f.sql}-${i}`}
                          type="button"
                          onClick={() => {
                            onInsert(f.snippet)
                            setOpen(false)
                          }}
                          title={f.desc}
                          className="group flex w-full items-center justify-between gap-2 rounded-md px-2 py-1 text-left transition-colors hover:bg-primary/10"
                        >
                          <span className="flex min-w-0 flex-col">
                            <span className="truncate text-[11px] font-medium text-foreground group-hover:text-primary">
                              {f.label}
                            </span>
                            <span className="truncate text-[9px] leading-tight text-muted-foreground/70">
                              {f.desc}
                            </span>
                          </span>
                          <span className="shrink-0 rounded bg-muted px-1 py-px font-mono text-[9px] font-semibold text-muted-foreground/70 group-hover:bg-primary/15 group-hover:text-primary/80">
                            {f.sql}
                          </span>
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </>,
          document.body,
        )
      : null

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 rounded-md border border-input bg-background px-2 py-1 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
      >
        <Sparkles className="size-3" />
        Funções
        <ChevronDown className={cn("size-3 transition-transform", open && "rotate-180")} />
      </button>
      {popover}
    </>
  )
}

function AdvancedMode({
  template,
  onChange,
  upstreamFields,
}: {
  template: string
  onChange: (next: string) => void
  upstreamFields: string[]
}) {
  const upstreamFieldObjs = upstreamFields.map((name) => ({ name }))

  function insertSnippet(snippet: string) {
    const sep = template && !template.endsWith(" ") ? " " : ""
    onChange(template + sep + snippet)
  }

  return (
    <ExpressionEditor
      template={template}
      onChange={onChange}
      upstreamFields={upstreamFieldObjs}
      allowVariables={true}
      placeholder="Ex.: {{quantidade}} * {{preco_unitario}} - COALESCE({{desconto}}, 0)"
      size="md"
      trailingControls={<FunctionsMenu onInsert={insertSnippet} />}
    />
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Mode selector (4 abas)
// ════════════════════════════════════════════════════════════════════════════

const MODE_META: { id: Mode; label: string; icon: typeof Calculator; desc: string }[] = [
  { id: "calc",     label: "Cálculo",   icon: Calculator, desc: "Operações com colunas e números (+, −, ×, ÷)" },
  { id: "cond",     label: "Condição",  icon: GitBranch,  desc: "Lógica SE / ENTÃO / SENÃO" },
  { id: "text",     label: "Texto",     icon: Type,       desc: "Transformar texto (maiúsculas, espaços, etc.)" },
  { id: "advanced", label: "Avançado",  icon: Code2,      desc: "Expressão SQL livre (DuckDB)" },
]

function ModeSelector({
  value,
  onChange,
}: {
  value: Mode
  onChange: (m: Mode) => void
}) {
  return (
    <div className="grid grid-cols-4 gap-1 rounded-md border border-border bg-muted/30 p-0.5">
      {MODE_META.map((m) => {
        const Icon = m.icon
        const active = value === m.id
        return (
          <button
            key={m.id}
            type="button"
            onClick={() => onChange(m.id)}
            title={m.desc}
            className={cn(
              "flex items-center justify-center gap-1 rounded px-1.5 py-1 text-[11px] font-medium transition-colors",
              active
                ? "bg-background text-primary shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3.5" />
            <span>{m.label}</span>
          </button>
        )
      })}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Estados padrões
// ════════════════════════════════════════════════════════════════════════════

function defaultCalc(): CalcState {
  return {
    operands: [
      { kind: "field", value: "" },
      { kind: "field", value: "" },
    ],
    operators: ["*"],
    wrapper: "none",
  }
}

function defaultCond(): CondState {
  return {
    branches: [
      {
        left: { kind: "field", value: "" },
        op: ">",
        right: { kind: "number", value: "0" },
        then: { kind: "text", value: "" },
      },
    ],
    fallback: { kind: "text", value: "" },
  }
}

function defaultText(): TextState {
  return { source: "", transforms: [] }
}

// ════════════════════════════════════════════════════════════════════════════
// Card de uma expressão
// ════════════════════════════════════════════════════════════════════════════

function ExpressionCard({
  expression,
  index,
  upstreamFields,
  onUpdate,
  onRemove,
  collapsed,
  onToggleCollapse,
}: {
  expression: MathExpression
  index: number
  upstreamFields: string[]
  onUpdate: (next: MathExpression) => void
  onRemove: () => void
  collapsed: boolean
  onToggleCollapse: () => void
}) {
  const mode = detectMode(expression)

  // Compila o estado atual em SQL e propaga pra ``expression`` (campo lido pelo
  // backend). Mantemos os estados específicos de cada modo no JSON (com prefixo
  // ``_``) pra round-trip lossless ao reabrir o nó.
  function commit(patch: Partial<MathExpression>, recompile = true) {
    const next: MathExpression = { ...expression, ...patch }
    if (recompile) {
      let sql = ""
      switch (next._mode ?? mode) {
        case "calc":
          if (next._calc) sql = compileCalc(next._calc)
          break
        case "cond":
          if (next._cond) sql = compileCond(next._cond)
          break
        case "text":
          if (next._text) sql = compileText(next._text)
          break
        case "advanced":
          sql = templateToSql(next._advanced ?? "")
          break
      }
      next.expression = sql
    }
    onUpdate(next)
  }

  function changeMode(nextMode: Mode) {
    const patch: Partial<MathExpression> = { _mode: nextMode }
    // Inicializa estado do novo modo se ainda não existir.
    if (nextMode === "calc" && !expression._calc) patch._calc = defaultCalc()
    if (nextMode === "cond" && !expression._cond) patch._cond = defaultCond()
    if (nextMode === "text" && !expression._text) patch._text = defaultText()
    if (nextMode === "advanced" && expression._advanced === undefined) {
      patch._advanced = sqlToTemplate(expression.expression, upstreamFields)
    }
    commit(patch)
  }

  return (
    <div className="rounded-lg border border-border bg-muted/20">
      {/* Header */}
      <div className="flex items-center gap-1.5 p-2.5">
        <span className="flex size-5 shrink-0 items-center justify-center rounded text-[10px] font-semibold text-muted-foreground/50">
          {index + 1}
        </span>
        <input
          type="text"
          value={expression.target_column}
          onChange={(e) => commit({ target_column: e.target.value }, false)}
          placeholder="nome_da_nova_coluna"
          className="h-7 min-w-0 flex-1 rounded-md border border-input bg-background px-2 text-xs font-medium text-foreground outline-none placeholder:font-normal placeholder:text-muted-foreground/60 focus:ring-1 focus:ring-primary"
        />
        <button
          type="button"
          onClick={onToggleCollapse}
          title={collapsed ? "Expandir" : "Minimizar"}
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground/50 transition-colors hover:bg-muted hover:text-foreground"
        >
          <ChevronDown
            className={cn(
              "size-3.5 transition-transform duration-150",
              collapsed && "-rotate-90",
            )}
          />
        </button>
        <button
          type="button"
          onClick={onRemove}
          className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
          aria-label="Remover expressão"
        >
          <Trash2 className="size-3" />
        </button>
      </div>

      {/* Resumo colapsado */}
      {collapsed && (
        <div className="px-2.5 pb-2 -mt-1 truncate font-mono text-[10px] text-muted-foreground">
          {expression.expression || (
            <em className="text-muted-foreground/50 not-italic">vazio</em>
          )}
        </div>
      )}

      {/* Conteúdo expandido */}
      {!collapsed && (
        <div className="space-y-2.5 px-2.5 pb-2.5">
          <ModeSelector value={mode} onChange={changeMode} />

          {mode === "calc" && (
            <CalcMode
              state={expression._calc ?? defaultCalc()}
              onChange={(next) => commit({ _calc: next })}
              upstreamFields={upstreamFields}
            />
          )}
          {mode === "cond" && (
            <CondMode
              state={expression._cond ?? defaultCond()}
              onChange={(next) => commit({ _cond: next })}
              upstreamFields={upstreamFields}
            />
          )}
          {mode === "text" && (
            <TextMode
              state={expression._text ?? defaultText()}
              onChange={(next) => commit({ _text: next })}
              upstreamFields={upstreamFields}
            />
          )}
          {mode === "advanced" && (
            <AdvancedMode
              template={
                expression._advanced ??
                sqlToTemplate(expression.expression, upstreamFields)
              }
              onChange={(next) => commit({ _advanced: next })}
              upstreamFields={upstreamFields}
            />
          )}

          {/* Preview do SQL gerado (debug-friendly, ajuda usuário a aprender) */}
          {expression.expression && mode !== "advanced" && (
            <div className="rounded-md border border-dashed border-border bg-background/40 px-2 py-1.5">
              <p className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50">
                SQL gerado
              </p>
              <code className="mt-0.5 block break-all font-mono text-[10px] leading-snug text-muted-foreground">
                {expression.expression}
              </code>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ════════════════════════════════════════════════════════════════════════════
// Componente principal
// ════════════════════════════════════════════════════════════════════════════

export function MathConfig({ data, onUpdate }: MathConfigProps) {
  const upstreamFields = useUpstreamFields()

  const expressions: MathExpression[] = Array.isArray(data.expressions)
    ? (data.expressions as MathExpression[])
    : []

  const [collapsed, setCollapsed] = useState<Set<number>>(new Set())
  const [isDragOver, setIsDragOver] = useState(false)

  function setExpressions(next: MathExpression[]) {
    onUpdate({ ...data, expressions: next })
  }

  function addExpression(initial?: Partial<MathExpression>) {
    const fresh: MathExpression = {
      target_column: "",
      expression: "",
      _mode: "calc",
      _calc: defaultCalc(),
      ...initial,
    }
    setExpressions([...expressions, fresh])
  }

  function removeExpression(i: number) {
    setExpressions(expressions.filter((_, idx) => idx !== i))
    setCollapsed((prev) => {
      const next = new Set<number>()
      for (const idx of prev) {
        if (idx < i) next.add(idx)
        else if (idx > i) next.add(idx - 1)
      }
      return next
    })
  }

  function updateExpression(i: number, next: MathExpression) {
    setExpressions(expressions.map((e, idx) => (idx === i ? next : e)))
  }

  function toggleCollapse(i: number) {
    setCollapsed((prev) => {
      const next = new Set(prev)
      if (next.has(i)) next.delete(i)
      else next.add(i)
      return next
    })
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setIsDragOver(false)
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (!field) return
    const calc = defaultCalc()
    calc.operands[0] = { kind: "field", value: field }
    addExpression({
      target_column: `${field}_calc`,
      _mode: "calc",
      _calc: calc,
      expression: compileCalc(calc),
    })
  }

  return (
    <div className="space-y-3">
      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Expressões
          </label>
          {expressions.length > 0 && (
            <button
              type="button"
              onClick={() => {
                const allCollapsed = expressions.every((_, i) => collapsed.has(i))
                setCollapsed(
                  allCollapsed
                    ? new Set()
                    : new Set(expressions.map((_, i) => i)),
                )
              }}
              className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground"
            >
              {expressions.every((_, i) => collapsed.has(i)) ? (
                <>
                  <ChevronsUpDown className="size-3" /> Expandir todos
                </>
              ) : (
                <>
                  <ChevronsDownUp className="size-3" /> Minimizar todos
                </>
              )}
            </button>
          )}
        </div>
        <p className="mb-2 text-[10px] text-muted-foreground/70">
          Cada linha cria uma nova coluna. Escolha um modo: cálculo, condição
          (se/então), texto, ou SQL avançado.
        </p>

        <div className="space-y-2">
          {expressions.map((exp, i) => (
            <ExpressionCard
              key={i}
              expression={exp}
              index={i}
              upstreamFields={upstreamFields}
              onUpdate={(next) => updateExpression(i, next)}
              onRemove={() => removeExpression(i)}
              collapsed={collapsed.has(i)}
              onToggleCollapse={() => toggleCollapse(i)}
            />
          ))}
        </div>

        {/* Drop zone / Add button */}
        <div
          onDragOver={(e) => {
            if (!e.dataTransfer.types.includes("application/x-shift-field")) return
            e.preventDefault()
            e.dataTransfer.dropEffect = "copy"
            setIsDragOver(true)
          }}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDrop}
          onClick={() => addExpression()}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed py-3 text-[11px] font-medium transition-all",
            isDragOver
              ? "border-primary bg-primary/5 text-primary"
              : "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
          {isDragOver ? (
            <>Soltar campo aqui</>
          ) : (
            <>
              <span className="text-muted-foreground/50">Arraste um campo aqui</span>
              <span className="text-muted-foreground/30">ou</span>
              <span className="flex items-center gap-1">
                <Plus className="size-3" />
                Adicionar expressão
              </span>
            </>
          )}
        </div>

        {expressions.length === 0 && upstreamFields.length === 0 && (
          <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground/70">
            Execute o nó anterior para ver os campos disponíveis e arrastá-los aqui.
          </p>
        )}
      </div>
    </div>
  )
}
