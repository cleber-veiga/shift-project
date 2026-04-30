"use client"

import { AlertTriangle, Plus, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import { FieldChipPicker } from "@/components/workflow/nodes/field-chip-picker"

type Operation = "sum" | "count" | "avg" | "max" | "min"

const OPERATIONS: { value: Operation; label: string }[] = [
  { value: "sum", label: "SUM" },
  { value: "count", label: "COUNT" },
  { value: "avg", label: "AVG" },
  { value: "max", label: "MAX" },
  { value: "min", label: "MIN" },
]

interface AggregationItem {
  column?: string | null
  operation: Operation
  alias: string
}

interface AggregatorConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

function defaultAlias(op: Operation, col: string | null | undefined): string {
  const c = col && col.trim() ? col.trim() : null
  if (op === "count" && !c) return "count"
  return `${op}_${c ?? "value"}`
}

export function AggregatorConfig({ data, onUpdate }: AggregatorConfigProps) {
  const upstreamFields = useUpstreamFields()

  const groupBy: string[] = Array.isArray(data.group_by)
    ? (data.group_by as string[])
    : []
  const aggregations: AggregationItem[] = Array.isArray(data.aggregations)
    ? (data.aggregations as AggregationItem[])
    : []

  // ── Group By handlers ──────────────────────────────────────────────────
  function addGroupColumn(field?: string) {
    if (field && groupBy.includes(field)) return
    onUpdate({ ...data, group_by: [...groupBy, field ?? ""] })
  }

  function removeGroupColumn(i: number) {
    onUpdate({ ...data, group_by: groupBy.filter((_, idx) => idx !== i) })
  }

  function updateGroupColumn(i: number, value: string) {
    onUpdate({
      ...data,
      group_by: groupBy.map((c, idx) => (idx === i ? value : c)),
    })
  }

  function handleDropGroup(e: React.DragEvent) {
    e.preventDefault()
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) addGroupColumn(field)
  }

  // ── Aggregations handlers ──────────────────────────────────────────────
  function addAggregation(field?: string) {
    const op: Operation = "sum"
    const column = field ?? ""
    const next: AggregationItem = {
      column: column || null,
      operation: op,
      alias: defaultAlias(op, column),
    }
    onUpdate({ ...data, aggregations: [...aggregations, next] })
  }

  function removeAggregation(i: number) {
    onUpdate({
      ...data,
      aggregations: aggregations.filter((_, idx) => idx !== i),
    })
  }

  function updateAggregation(i: number, patch: Partial<AggregationItem>) {
    const current = aggregations[i]
    const merged: AggregationItem = { ...current, ...patch }

    // Auto-regenera o alias quando ele ainda corresponde ao padrão antigo
    // (sinal de que o usuário não personalizou). Assim trocar SUM→AVG
    // atualiza "sum_amount" → "avg_amount" sem sobrescrever um alias custom.
    const previousDefault = defaultAlias(current.operation, current.column)
    if (current.alias === previousDefault) {
      merged.alias = defaultAlias(merged.operation, merged.column)
    }

    onUpdate({
      ...data,
      aggregations: aggregations.map((a, idx) => (idx === i ? merged : a)),
    })
  }

  function handleDropAggregation(e: React.DragEvent) {
    e.preventDefault()
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) addAggregation(field)
  }

  return (
    <div className="space-y-5">
      {/* ── Agrupar por ───────────────────────────────────────────────── */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Agrupar por
        </label>
        <p className="mb-2 text-[10px] text-muted-foreground/70">
          Colunas usadas no GROUP BY. Vazio agrega todas as linhas em um único registro.
        </p>
        <div className="space-y-1.5">
          {groupBy.map((col, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <FieldChipPicker
                  value={col}
                  onChange={(v) => updateGroupColumn(i, v)}
                  placeholder="selecionar coluna"
                  upstreamFields={upstreamFields}
                />
              </div>
              <button
                type="button"
                onClick={() => removeGroupColumn(i)}
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
            if (e.dataTransfer.types.includes("application/x-shift-field")) {
              e.preventDefault()
              e.dataTransfer.dropEffect = "copy"
            }
          }}
          onDrop={handleDropGroup}
          onClick={() => addGroupColumn()}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed py-2.5 text-[11px] font-medium transition-all",
            "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
          <Plus className="size-3" />
          Adicionar coluna de agrupamento
        </div>
      </div>

      {/* ── Agregações ─────────────────────────────────────────────────── */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Agregações
        </label>
        <p className="mb-2 text-[10px] text-muted-foreground/70">
          Cada linha gera uma coluna no resultado com o nome do alias.
        </p>

        <div className="space-y-2">
          {aggregations.map((agg, i) => {
            const op = agg.operation
            const col = agg.column ?? ""
            const isCount = op === "count"
            return (
              <div
                key={i}
                className="rounded-lg border border-border bg-muted/20 p-2"
              >
                <div className="grid grid-cols-[100px,1fr] gap-2">
                  {/* Operação */}
                  <select
                    value={op}
                    onChange={(e) =>
                      updateAggregation(i, {
                        operation: e.target.value as Operation,
                      })
                    }
                    className="h-8 rounded-md border border-input bg-background px-2 text-xs font-semibold text-foreground outline-none focus:ring-1 focus:ring-primary"
                  >
                    {OPERATIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>

                  {/* Coluna (chip linkado) */}
                  <FieldChipPicker
                    value={col}
                    onChange={(v) =>
                      updateAggregation(i, { column: v || null })
                    }
                    placeholder="selecionar coluna"
                    allowAllRows={isCount}
                    upstreamFields={upstreamFields}
                  />
                </div>

                {/* Alias */}
                <div className="mt-2 flex items-center gap-2">
                  <span className="text-[10px] uppercase tracking-wider text-muted-foreground/70">
                    Alias
                  </span>
                  <input
                    type="text"
                    value={agg.alias}
                    onChange={(e) =>
                      updateAggregation(i, { alias: e.target.value })
                    }
                    placeholder={defaultAlias(op, col)}
                    className="h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                  />
                  <button
                    type="button"
                    onClick={() => removeAggregation(i)}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                    aria-label="Remover agregação"
                  >
                    <Trash2 className="size-3" />
                  </button>
                </div>

                {/* Aviso quando coluna obrigatória está vazia */}
                {!isCount && !col && (
                  <p className="mt-1.5 text-[10px] text-amber-600 dark:text-amber-400">
                    {OPERATIONS.find((o) => o.value === op)?.label} requer uma coluna.
                  </p>
                )}
              </div>
            )
          })}
        </div>

        <div
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes("application/x-shift-field")) {
              e.preventDefault()
              e.dataTransfer.dropEffect = "copy"
            }
          }}
          onDrop={handleDropAggregation}
          onClick={() => addAggregation()}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed py-2.5 text-[11px] font-medium transition-all",
            "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
          <Plus className="size-3" />
          Adicionar agregação
        </div>

        {aggregations.length === 0 && (
          <div className="mt-2 flex items-start gap-2 rounded-lg border border-amber-500/40 bg-amber-500/5 p-2.5">
            <AlertTriangle className="size-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div className="min-w-0 flex-1 space-y-1.5">
              <p className="text-[11px] font-medium text-amber-700 dark:text-amber-300">
                Pelo menos uma agregação é obrigatória.
              </p>
              <p className="text-[10px] leading-relaxed text-amber-700/80 dark:text-amber-300/80">
                {groupBy.length > 0
                  ? "Você definiu o agrupamento, agora escolha o que calcular para cada grupo (ex.: contar registros, somar valores)."
                  : "Adicione uma agregação como SUM, COUNT ou AVG para o nó produzir resultado."}
              </p>
              <button
                type="button"
                onClick={() => {
                  onUpdate({
                    ...data,
                    aggregations: [
                      { column: null, operation: "count", alias: "total" },
                    ],
                  })
                }}
                className="inline-flex items-center gap-1 rounded-md bg-amber-600/15 px-2 py-1 text-[10px] font-semibold text-amber-700 transition-colors hover:bg-amber-600/25 dark:text-amber-300"
              >
                <Plus className="size-2.5" />
                Adicionar contagem de registros
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
