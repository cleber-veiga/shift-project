"use client"

import { Plus, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"

type ByType = "all_numeric" | "all_string"

interface UnpivotConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

export function UnpivotConfig({ data, onUpdate }: UnpivotConfigProps) {
  const upstreamFields = useUpstreamFields()

  const indexColumns: string[] = Array.isArray(data.index_columns)
    ? (data.index_columns as string[])
    : []
  const valueColumns: string[] = Array.isArray(data.value_columns)
    ? (data.value_columns as string[])
    : []
  const byType = (data.by_type as ByType | null) ?? null
  const variableColumnName = (data.variable_column_name as string) ?? "variable"
  const valueColumnName = (data.value_column_name as string) ?? "value"
  const castValueTo = (data.cast_value_to as string | null) ?? null

  const useByType = byType !== null || valueColumns.length === 0

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

  function addValueColumn(field?: string) {
    if (field && valueColumns.includes(field)) return
    onUpdate({ ...data, value_columns: [...valueColumns, field ?? ""], by_type: null })
  }

  function removeValueColumn(i: number) {
    onUpdate({ ...data, value_columns: valueColumns.filter((_, idx) => idx !== i) })
  }

  function updateValueColumn(i: number, value: string) {
    onUpdate({
      ...data,
      value_columns: valueColumns.map((c, idx) => (idx === i ? value : c)),
    })
  }

  function setByType(bt: ByType | null) {
    onUpdate({ ...data, by_type: bt, value_columns: bt ? [] : valueColumns })
  }

  function handleDropIndex(e: React.DragEvent) {
    e.preventDefault()
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) addIndexColumn(field)
  }

  function handleDropValue(e: React.DragEvent) {
    e.preventDefault()
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) addValueColumn(field)
  }

  function ColumnSelect({
    value,
    onChange,
    placeholder,
  }: {
    value: string
    onChange: (v: string) => void
    placeholder: string
  }) {
    if (upstreamFields.length > 0) {
      return (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="">-- {placeholder} --</option>
          {upstreamFields.map((f) => (
            <option key={f} value={f}>
              {f}
            </option>
          ))}
        </select>
      )
    }
    return (
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="h-7 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
      />
    )
  }

  return (
    <div className="space-y-4">
      {/* Index columns */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Colunas de índice
        </label>
        <p className="mb-2 text-[10px] text-muted-foreground/70">
          Colunas que permanecem fixas (identificadoras da linha).
        </p>
        <div className="space-y-1.5">
          {indexColumns.map((col, i) => (
            <div key={i} className="flex items-center gap-2">
              <div className="flex-1">
                <ColumnSelect
                  value={col}
                  onChange={(v) => updateIndexColumn(i, v)}
                  placeholder="selecionar coluna"
                />
              </div>
              <button
                type="button"
                onClick={() => removeIndexColumn(i)}
                className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
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
          onDrop={handleDropIndex}
          onClick={() => addIndexColumn()}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed py-2.5 text-[11px] font-medium transition-all",
            "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
          <Plus className="size-3" />
          Adicionar coluna de índice
        </div>
      </div>

      {/* Value columns: explicit or by_type */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Colunas a expandir
        </label>

        {/* Mode toggle */}
        <div className="mb-3 flex gap-1.5">
          <button
            type="button"
            onClick={() => setByType(null)}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
              !byType
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            Explícitas
          </button>
          <button
            type="button"
            onClick={() => setByType("all_numeric")}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
              byType === "all_numeric"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            Numéricas
          </button>
          <button
            type="button"
            onClick={() => setByType("all_string")}
            className={cn(
              "rounded-md px-2.5 py-1 text-[11px] font-medium transition-colors",
              byType === "all_string"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            Texto
          </button>
        </div>

        {byType ? (
          <p className="text-[10px] text-muted-foreground/70">
            {byType === "all_numeric"
              ? "Todas as colunas numéricas (excluindo as de índice) serão expandidas automaticamente."
              : "Todas as colunas de texto (excluindo as de índice) serão expandidas automaticamente."}
          </p>
        ) : (
          <>
            <div className="space-y-1.5">
              {valueColumns.map((col, i) => (
                <div key={i} className="flex items-center gap-2">
                  <div className="flex-1">
                    <ColumnSelect
                      value={col}
                      onChange={(v) => updateValueColumn(i, v)}
                      placeholder="selecionar coluna"
                    />
                  </div>
                  <button
                    type="button"
                    onClick={() => removeValueColumn(i)}
                    className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
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
              onDrop={handleDropValue}
              onClick={() => addValueColumn()}
              className={cn(
                "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed py-2.5 text-[11px] font-medium transition-all",
                "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
              )}
            >
              <Plus className="size-3" />
              Adicionar coluna de valor
            </div>
          </>
        )}
      </div>

      {/* Output column names */}
      <div className="grid grid-cols-2 gap-3">
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Col. variável
          </label>
          <input
            type="text"
            value={variableColumnName}
            onChange={(e) => onUpdate({ ...data, variable_column_name: e.target.value })}
            placeholder="variable"
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Col. valor
          </label>
          <input
            type="text"
            value={valueColumnName}
            onChange={(e) => onUpdate({ ...data, value_column_name: e.target.value })}
            placeholder="value"
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
        </div>
      </div>

      {/* Cast value to */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Converter valores para (opcional)
        </label>
        <select
          value={castValueTo ?? ""}
          onChange={(e) => onUpdate({ ...data, cast_value_to: e.target.value || null })}
          className="h-8 w-full rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="">-- manter tipo original --</option>
          <option value="VARCHAR">VARCHAR (texto)</option>
          <option value="DOUBLE">DOUBLE (decimal)</option>
          <option value="BIGINT">BIGINT (inteiro)</option>
        </select>
      </div>
    </div>
  )
}
