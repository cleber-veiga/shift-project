"use client"

import { Plus, Trash2, ArrowUp, ArrowDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"

interface OrderByItem {
  column: string
  direction: "asc" | "desc"
}

interface RecordIdConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

function normalizeOrderBy(raw: unknown): OrderByItem {
  const c = (raw ?? {}) as Record<string, unknown>
  return {
    column: (c.column as string) ?? "",
    direction: (c.direction as "asc" | "desc") ?? "asc",
  }
}

export function RecordIdConfig({ data, onUpdate }: RecordIdConfigProps) {
  const upstreamFields = useUpstreamFields()

  const idColumn = (data.id_column as string) ?? "id"
  const startAt = (data.start_at as number) ?? 1
  const partitionBy: string[] = Array.isArray(data.partition_by)
    ? (data.partition_by as string[])
    : []
  const orderBy: OrderByItem[] = Array.isArray(data.order_by)
    ? (data.order_by as unknown[]).map(normalizeOrderBy)
    : []

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  // --- Partition by ---
  function addPartitionField(field?: string) {
    update({ partition_by: [...partitionBy, field ?? ""] })
  }

  function removePartitionField(i: number) {
    update({ partition_by: partitionBy.filter((_, idx) => idx !== i) })
  }

  function updatePartitionField(i: number, val: string) {
    update({ partition_by: partitionBy.map((v, idx) => (idx === i ? val : v)) })
  }

  // --- Order by ---
  function addOrderBy(field?: string) {
    update({ order_by: [...orderBy, { column: field ?? "", direction: "asc" }] })
  }

  function removeOrderBy(i: number) {
    update({ order_by: orderBy.filter((_, idx) => idx !== i) })
  }

  function updateOrderBy(i: number, patch: Partial<OrderByItem>) {
    update({ order_by: orderBy.map((ob, idx) => (idx === i ? { ...ob, ...patch } : ob)) })
  }

  function renderColumnSelect(
    value: string,
    onChange: (v: string) => void,
    placeholder = "coluna...",
  ) {
    if (upstreamFields.length > 0) {
      return (
        <select
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
        >
          <option value="">-- selecionar --</option>
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
        className="h-7 flex-1 rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
      />
    )
  }

  return (
    <div className="space-y-4">
      {/* ID column name */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Nome da coluna de ID
        </label>
        <input
          type="text"
          value={idColumn}
          onChange={(e) => update({ id_column: e.target.value || "id" })}
          placeholder="id"
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Start at */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Iniciar em
        </label>
        <input
          type="number"
          min={1}
          value={startAt}
          onChange={(e) => update({ start_at: parseInt(e.target.value, 10) || 1 })}
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Partition by */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Reiniciar por grupo (Partition By)
        </label>
        <div className="space-y-1.5">
          {partitionBy.map((col, i) => (
            <div key={i} className="flex items-center gap-2">
              {renderColumnSelect(col, (v) => updatePartitionField(i, v), "coluna de grupo...")}
              <button
                type="button"
                onClick={() => removePartitionField(i)}
                className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 className="size-3" />
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() => addPartitionField()}
          className="mt-1.5 flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <Plus className="size-3" />
          Adicionar grupo
        </button>
        <p className="mt-1 text-[10px] text-muted-foreground/70">
          Opcional. Quando definido, a numeração recomeça em cada combinação de valores.
        </p>
      </div>

      {/* Order by */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Ordenar antes de numerar (Order By)
        </label>
        <div className="space-y-1.5">
          {orderBy.map((ob, i) => (
            <div key={i} className="flex items-center gap-2">
              {renderColumnSelect(ob.column, (v) => updateOrderBy(i, { column: v }), "coluna...")}
              <button
                type="button"
                onClick={() =>
                  updateOrderBy(i, { direction: ob.direction === "asc" ? "desc" : "asc" })
                }
                className={cn(
                  "flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium transition-colors",
                  ob.direction === "asc"
                    ? "bg-primary/10 text-primary"
                    : "bg-muted text-muted-foreground hover:text-foreground",
                )}
              >
                {ob.direction === "asc" ? (
                  <ArrowUp className="size-3" />
                ) : (
                  <ArrowDown className="size-3" />
                )}
                {ob.direction.toUpperCase()}
              </button>
              <button
                type="button"
                onClick={() => removeOrderBy(i)}
                className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
              >
                <Trash2 className="size-3" />
              </button>
            </div>
          ))}
        </div>
        <button
          type="button"
          onClick={() => addOrderBy()}
          className="mt-1.5 flex items-center gap-1 text-[11px] text-muted-foreground transition-colors hover:text-foreground"
        >
          <Plus className="size-3" />
          Adicionar coluna de ordem
        </button>
        <p className="mt-1 text-[10px] text-muted-foreground/70">
          Opcional. Sem ordenação, a sequência não é determinística.
        </p>
      </div>
    </div>
  )
}
