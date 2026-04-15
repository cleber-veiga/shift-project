"use client"

import { useCallback, useState } from "react"
import { GripVertical, Plus, Trash2, XCircle } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"

// ─── Types ────────────────────────────────────────────────────────────────────

interface Condition {
  field: string
  operator: string
  value: string
}

interface FilterConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ─── Operators ───────────────────────────────────────────────────────────────

const OPERATORS = [
  { value: "eq",           label: "é igual a",        needsValue: true },
  { value: "neq",          label: "é diferente de",   needsValue: true },
  { value: "contains",     label: "contém",           needsValue: true },
  { value: "startswith",   label: "começa com",       needsValue: true },
  { value: "endswith",     label: "termina com",      needsValue: true },
  { value: "gt",           label: "maior que",        needsValue: true },
  { value: "gte",          label: "maior ou igual a", needsValue: true },
  { value: "lt",           label: "menor que",        needsValue: true },
  { value: "lte",          label: "menor ou igual a", needsValue: true },
  { value: "is_null",      label: "é nulo",           needsValue: false },
  { value: "is_not_null",  label: "não é nulo",       needsValue: false },
] as const

function operatorNeedsValue(op: string): boolean {
  return OPERATORS.find((o) => o.value === op)?.needsValue !== false
}

// ─── Component ────────────────────────────────────────────────────────────────

export function FilterConfig({ data, onUpdate }: FilterConfigProps) {
  const upstreamFields = useUpstreamFields()
  const [isDragOver, setIsDragOver] = useState(false)
  const [dragOverRowIdx, setDragOverRowIdx] = useState<number | null>(null)

  const conditions: Condition[] = Array.isArray(data.conditions)
    ? (data.conditions as Condition[])
    : []
  const logic = (data.logic as string) ?? "and"

  const setConditions = useCallback(
    (next: Condition[]) => onUpdate({ ...data, conditions: next }),
    [data, onUpdate],
  )

  function addCondition(field?: string) {
    setConditions([...conditions, { field: field ?? "", operator: "eq", value: "" }])
  }

  function removeCondition(index: number) {
    setConditions(conditions.filter((_, i) => i !== index))
  }

  function updateCondition(index: number, key: keyof Condition, value: string) {
    setConditions(
      conditions.map((c, i) => (i === index ? { ...c, [key]: value } : c)),
    )
  }

  // ─── Drag & Drop ──────────────────────────────────────────────────────────

  function handleDropOnZone(e: React.DragEvent) {
    e.preventDefault()
    setIsDragOver(false)
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) addCondition(field)
  }

  function handleDropOnRow(e: React.DragEvent, index: number) {
    e.preventDefault()
    e.stopPropagation()
    setDragOverRowIdx(null)
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) updateCondition(index, "field", field)
  }

  function handleDragOverZone(e: React.DragEvent) {
    e.preventDefault()
    e.dataTransfer.dropEffect = "copy"
    setIsDragOver(true)
  }

  function handleDragOverRow(e: React.DragEvent, index: number) {
    e.preventDefault()
    e.stopPropagation()
    e.dataTransfer.dropEffect = "copy"
    setDragOverRowIdx(index)
  }

  // Fields already used
  const usedFields = new Set(conditions.map((c) => c.field))

  return (
    <div className="space-y-4">
      {/* Logic selector */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Lógica
        </label>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => onUpdate({ ...data, logic: "and" })}
            className={cn(
              "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              logic === "and"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            AND — todas as condições
          </button>
          <button
            type="button"
            onClick={() => onUpdate({ ...data, logic: "or" })}
            className={cn(
              "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              logic === "or"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            OR — qualquer condição
          </button>
        </div>
      </div>

      {/* Conditions */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Condições
        </label>

        <div className="space-y-2">
          {conditions.map((cond, i) => {
            const needsValue = operatorNeedsValue(cond.operator)

            return (
              <div
                key={i}
                className={cn(
                  "rounded-lg border border-border bg-background p-2.5 transition-colors",
                  dragOverRowIdx === i && "border-primary bg-primary/5",
                )}
                onDragOver={(e) => handleDragOverRow(e, i)}
                onDragLeave={() => setDragOverRowIdx(null)}
                onDrop={(e) => handleDropOnRow(e, i)}
              >
                {/* Row 1: Field + Operator */}
                <div className="flex items-center gap-2">
                  {/* Field */}
                  <div className="flex-1">
                    {upstreamFields.length > 0 ? (
                      <select
                        value={cond.field}
                        onChange={(e) => updateCondition(i, "field", e.target.value)}
                        className={cn(
                          "h-8 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary",
                          cond.field ? "text-foreground" : "text-muted-foreground",
                        )}
                      >
                        <option value="">Selecionar campo...</option>
                        {upstreamFields.map((f) => (
                          <option key={f} value={f}>
                            {f}
                          </option>
                        ))}
                      </select>
                    ) : (
                      <input
                        type="text"
                        value={cond.field}
                        onChange={(e) => updateCondition(i, "field", e.target.value)}
                        placeholder="nome_do_campo"
                        className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                      />
                    )}
                  </div>

                  {/* Operator */}
                  <select
                    value={cond.operator}
                    onChange={(e) => updateCondition(i, "operator", e.target.value)}
                    className="h-8 shrink-0 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
                  >
                    {OPERATORS.map((op) => (
                      <option key={op.value} value={op.value}>
                        {op.label}
                      </option>
                    ))}
                  </select>

                  {/* Delete */}
                  <button
                    type="button"
                    onClick={() => removeCondition(i)}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    aria-label="Remover condição"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>

                {/* Row 2: Value (if operator needs it) */}
                {needsValue && (
                  <div className="mt-2">
                    <input
                      type="text"
                      value={cond.value}
                      onChange={(e) => updateCondition(i, "value", e.target.value)}
                      placeholder="Valor para comparar..."
                      className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                    />
                  </div>
                )}

                {/* Logic badge between conditions */}
                {i < conditions.length - 1 && (
                  <div className="mt-2 flex justify-center">
                    <span className="rounded-full bg-muted px-2.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      {logic}
                    </span>
                  </div>
                )}
              </div>
            )
          })}
        </div>

        {/* Drop zone + Add button */}
        <div
          onDragOver={handleDragOverZone}
          onDragLeave={() => setIsDragOver(false)}
          onDrop={handleDropOnZone}
          onClick={() => addCondition()}
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
              <span className="text-muted-foreground/50">
                Arraste campos da entrada aqui
              </span>
              <span className="text-muted-foreground/30">ou</span>
              <span className="flex items-center gap-1">
                <Plus className="size-3" />
                Adicionar condição
              </span>
            </>
          )}
        </div>

        {/* Hint */}
        {upstreamFields.length === 0 && conditions.length === 0 && (
          <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground/70">
            Execute o nó anterior para ver os campos disponíveis,
            ou adicione condições manualmente.
          </p>
        )}
      </div>
    </div>
  )
}
