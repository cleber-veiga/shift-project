"use client"

import { useCallback } from "react"
import { AlertTriangle, GripVertical, Plus, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import {
  type ParameterValue,
  type UpstreamField,
  createFixed,
  createDynamic,
} from "@/lib/workflow/parameter-value"
import { usePredictedSchema } from "@/lib/workflow/use-predicted-schema"
import { ValueInput } from "@/components/workflow/value-input/ValueInput"

// ─── Helpers ──────────────────────────────────────────────────────────────────

function extractFieldRefs(pv: ParameterValue): string[] {
  if (pv.mode !== "dynamic") return []
  const matches = [...pv.template.matchAll(/\{\{([^}]+)\}\}/g)]
  return matches.map((m) => m[1].trim())
}

function UnavailableColumnBadge({ columns }: { columns: string[] }) {
  if (columns.length === 0) return null
  return (
    <div className="mt-1 flex flex-wrap gap-1">
      {columns.map((col) => (
        <span
          key={col}
          className="inline-flex items-center gap-1 rounded-full bg-destructive/10 px-2 py-0.5 text-[10px] font-medium text-destructive"
          title={`A coluna '${col}' não existe no dataset upstream`}
        >
          <AlertTriangle className="size-2.5 shrink-0" />
          {col} não disponível
        </span>
      ))}
    </div>
  )
}

// ─── Types ────────────────────────────────────────────────────────────────────

interface Condition {
  left: ParameterValue
  operator: string
  right: ParameterValue
}

interface FilterConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
  workflowId?: string
  nodeId?: string
}

// ─── Operators ───────────────────────────────────────────────────────────────

const OPERATORS = [
  { value: "eq",          label: "é igual a",        needsValue: true },
  { value: "neq",         label: "é diferente de",   needsValue: true },
  { value: "contains",    label: "contém",            needsValue: true },
  { value: "startswith",  label: "começa com",        needsValue: true },
  { value: "endswith",    label: "termina com",       needsValue: true },
  { value: "gt",          label: "maior que",         needsValue: true },
  { value: "gte",         label: "maior ou igual a",  needsValue: true },
  { value: "lt",          label: "menor que",         needsValue: true },
  { value: "lte",         label: "menor ou igual a",  needsValue: true },
  { value: "is_null",     label: "é nulo",            needsValue: false },
  { value: "is_not_null", label: "não é nulo",        needsValue: false },
] as const

function operatorNeedsValue(op: string): boolean {
  return OPERATORS.find((o) => o.value === op)?.needsValue !== false
}

// ─── Legacy adapter ───────────────────────────────────────────────────────────

function normalizeCondition(raw: unknown): Condition {
  const c = (raw ?? {}) as Record<string, unknown>
  if ("left" in c || "right" in c) {
    return {
      left: (c.left as ParameterValue) ?? createFixed(""),
      operator: (c.operator as string) ?? "eq",
      right: (c.right as ParameterValue) ?? createFixed(""),
    }
  }
  // Legacy: { field, operator, value }
  const field = (c.field as string) ?? ""
  return {
    left: field ? createDynamic(`{{${field}}}`, []) : createFixed(""),
    operator: (c.operator as string) ?? "eq",
    right: createFixed(c.value != null ? String(c.value) : ""),
  }
}

// ─── Component ────────────────────────────────────────────────────────────────

export function FilterConfig({
  data,
  onUpdate,
  workflowId,
  nodeId,
}: FilterConfigProps) {
  const rawUpstreamFields = useUpstreamFields()
  // Schema previsto pelo backend tem prioridade sobre upstreamFields
  // (que veem só do último run); permite avisar sobre staleness antes
  // mesmo de o usuário rodar o workflow.
  const { schema: predictedSchema } = usePredictedSchema(workflowId, nodeId)
  const predictedColumnSet = predictedSchema
    ? new Set(predictedSchema.map((f) => f.name))
    : null
  const upstreamFieldSet = new Set(rawUpstreamFields)
  const upstreamFieldPVs: UpstreamField[] = rawUpstreamFields.map((f) => ({
    name: f,
  }))

  const conditions: Condition[] = Array.isArray(data.conditions)
    ? (data.conditions as unknown[]).map(normalizeCondition)
    : []
  const logic = (data.logic as string) ?? "and"

  const setConditions = useCallback(
    (next: Condition[]) => onUpdate({ ...data, conditions: next }),
    [data, onUpdate],
  )

  function addCondition(field?: string) {
    const left = field ? createDynamic(`{{${field}}}`, []) : createFixed("")
    setConditions([
      ...conditions,
      { left, operator: "eq", right: createFixed("") },
    ])
  }

  function removeCondition(index: number) {
    setConditions(conditions.filter((_, i) => i !== index))
  }

  function updateLeft(index: number, pv: ParameterValue) {
    setConditions(conditions.map((c, i) => (i === index ? { ...c, left: pv } : c)))
  }

  function updateRight(index: number, pv: ParameterValue) {
    setConditions(conditions.map((c, i) => (i === index ? { ...c, right: pv } : c)))
  }

  function updateOperator(index: number, op: string) {
    setConditions(conditions.map((c, i) => (i === index ? { ...c, operator: op } : c)))
  }

  // Drop zone creates a new condition with the field as left chip
  function handleDropOnZone(e: React.DragEvent) {
    e.preventDefault()
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) addCondition(field)
  }

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
            const leftRefs = extractFieldRefs(cond.left)
            // Prioriza schema previsto (backend); se ausente, cai pro
            // upstreamFields (vindo do último run); caso contrário, sem source
            // de verdade não há como invalidar.
            let unavailableCols: string[] = []
            if (predictedColumnSet) {
              unavailableCols = leftRefs.filter(
                (f) => !predictedColumnSet.has(f),
              )
            } else if (rawUpstreamFields.length > 0) {
              unavailableCols = leftRefs.filter(
                (f) => !upstreamFieldSet.has(f),
              )
            }

            return (
              <div
                key={i}
                className="rounded-lg border border-border bg-background p-2.5"
              >
                {/* Row 1: Left + Operator + Delete */}
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <ValueInput
                      value={cond.left}
                      onChange={(pv) => updateLeft(i, pv)}
                      upstreamFields={upstreamFieldPVs}
                      allowTransforms={true}
                      allowVariables={false}
                      placeholder="campo..."
                      size="sm"
                    />
                  </div>

                  <select
                    value={cond.operator}
                    onChange={(e) => updateOperator(i, e.target.value)}
                    className="h-7 shrink-0 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
                  >
                    {OPERATORS.map((op) => (
                      <option key={op.value} value={op.value}>
                        {op.label}
                      </option>
                    ))}
                  </select>

                  <button
                    type="button"
                    onClick={() => removeCondition(i)}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    aria-label="Remover condição"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>

                {/* Unavailable column warning */}
                <UnavailableColumnBadge columns={unavailableCols} />

                {/* Row 2: Right value (if operator needs it) */}
                {needsValue && (
                  <div className="mt-2">
                    <ValueInput
                      value={cond.right}
                      onChange={(pv) => updateRight(i, pv)}
                      upstreamFields={upstreamFieldPVs}
                      allowTransforms={true}
                      allowVariables={true}
                      placeholder="valor para comparar..."
                      size="sm"
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
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes("application/x-shift-field")) {
              e.preventDefault()
              e.dataTransfer.dropEffect = "copy"
            }
          }}
          onDrop={handleDropOnZone}
          onClick={() => addCondition()}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed py-3 text-[11px] font-medium transition-all",
            "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
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
        </div>

        {rawUpstreamFields.length === 0 && conditions.length === 0 && (
          <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground/70">
            Execute o nó anterior para ver os campos disponíveis,
            ou adicione condições manualmente.
          </p>
        )}
      </div>
    </div>
  )
}
