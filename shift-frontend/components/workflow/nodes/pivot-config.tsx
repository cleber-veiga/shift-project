"use client"

import { Plus, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import { FieldChipPicker } from "@/components/workflow/nodes/field-chip-picker"

type Aggregation = "sum" | "count" | "avg" | "max" | "min"

const AGGREGATIONS: { value: Aggregation; label: string }[] = [
  { value: "sum", label: "SUM" },
  { value: "count", label: "COUNT" },
  { value: "avg", label: "AVG" },
  { value: "max", label: "MAX" },
  { value: "min", label: "MIN" },
]

const FIELD_DRAG_TYPE = "application/x-shift-field"

interface PivotConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

export function PivotConfig({ data, onUpdate }: PivotConfigProps) {
  const upstreamFields = useUpstreamFields()

  const indexColumns: string[] = Array.isArray(data.index_columns)
    ? (data.index_columns as string[])
    : []
  const pivotColumn = (data.pivot_column as string) ?? ""
  const valueColumn = (data.value_column as string) ?? ""
  const aggregations: Aggregation[] = Array.isArray(data.aggregations)
    ? (data.aggregations as Aggregation[])
    : ["sum"]
  const maxPivotValues = (data.max_pivot_values as number) ?? 200

  function toggleAggregation(agg: Aggregation) {
    const next = aggregations.includes(agg)
      ? aggregations.filter((a) => a !== agg)
      : [...aggregations, agg]
    onUpdate({ ...data, aggregations: next.length ? next : ["sum"] })
  }

  function addIndexColumn(field?: string) {
    if (field && indexColumns.includes(field)) return
    onUpdate({ ...data, index_columns: [...indexColumns, field ?? ""] })
  }

  function removeIndexColumn(i: number) {
    onUpdate({ ...data, index_columns: indexColumns.filter((_, idx) => idx !== i) })
  }

  function updateIndexColumn(i: number, value: string) {
    onUpdate({
      ...data,
      index_columns: indexColumns.map((c, idx) => (idx === i ? value : c)),
    })
  }

  function handleDropIndex(e: React.DragEvent) {
    e.preventDefault()
    const field = e.dataTransfer.getData(FIELD_DRAG_TYPE)
    if (field) addIndexColumn(field)
  }

  return (
    <div className="space-y-4">
      {/* Colunas de índice */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Colunas de índice
        </label>
        <p className="mb-2 text-[10px] text-muted-foreground/70">
          Colunas que identificam cada linha no resultado (GROUP BY).
        </p>
        <div className="space-y-1.5">
          {indexColumns.map((col, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="min-w-0 flex-1">
                <FieldChipPicker
                  value={col}
                  onChange={(v) => updateIndexColumn(i, v)}
                  upstreamFields={upstreamFields}
                  placeholder="selecionar coluna"
                />
              </div>
              <button
                type="button"
                onClick={() => removeIndexColumn(i)}
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
            if (e.dataTransfer.types.includes(FIELD_DRAG_TYPE)) {
              e.preventDefault()
              e.dataTransfer.dropEffect = "copy"
            }
          }}
          onDrop={handleDropIndex}
          onClick={() => addIndexColumn()}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed py-2.5 text-[11px] font-medium transition-all",
            "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
          <span className="text-muted-foreground/50">Arraste um campo</span>
          <span className="text-muted-foreground/30">ou</span>
          <span className="flex items-center gap-1">
            <Plus className="size-3" />
            Adicionar coluna de índice
          </span>
        </div>
      </div>

      {/* Coluna pivot */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Coluna pivot
        </label>
        <p className="text-[10px] text-muted-foreground/70">
          Valores únicos desta coluna viram novas colunas.
        </p>
        <FieldChipPicker
          value={pivotColumn}
          onChange={(v) => onUpdate({ ...data, pivot_column: v })}
          upstreamFields={upstreamFields}
          placeholder="selecionar coluna"
        />
      </div>

      {/* Coluna de valor */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Coluna de valor
        </label>
        <FieldChipPicker
          value={valueColumn}
          onChange={(v) => onUpdate({ ...data, value_column: v })}
          upstreamFields={upstreamFields}
          placeholder="selecionar coluna"
        />
      </div>

      {/* Agregações */}
      <div className="space-y-2">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Agregações
        </label>
        <div className="flex flex-wrap gap-1.5">
          {AGGREGATIONS.map(({ value: agg, label }) => (
            <button
              key={agg}
              type="button"
              onClick={() => toggleAggregation(agg)}
              className={cn(
                "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
                aggregations.includes(agg)
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground",
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Limite de valores pivot */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Limite de valores pivot
        </label>
        <input
          type="number"
          min={1}
          max={1000}
          value={maxPivotValues}
          onChange={(e) =>
            onUpdate({ ...data, max_pivot_values: parseInt(e.target.value, 10) || 200 })
          }
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
        <p className="text-[10px] text-muted-foreground/70">
          Falha se a coluna pivot tiver mais valores únicos que este limite (máx. 1000).
        </p>
      </div>
    </div>
  )
}
