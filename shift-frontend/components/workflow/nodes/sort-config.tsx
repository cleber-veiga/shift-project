"use client"

import { Plus, Trash2, ArrowUp, ArrowDown } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"

interface SortColumn {
  column: string
  direction: "asc" | "desc"
  nulls_position?: "first" | "last" | null
}

interface SortConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

function normalizeSortColumn(raw: unknown): SortColumn {
  const c = (raw ?? {}) as Record<string, unknown>
  return {
    column: (c.column as string) ?? "",
    direction: (c.direction as "asc" | "desc") ?? "asc",
    nulls_position: (c.nulls_position as "first" | "last" | null) ?? null,
  }
}

export function SortConfig({ data, onUpdate }: SortConfigProps) {
  const upstreamFields = useUpstreamFields()

  const sortColumns: SortColumn[] = Array.isArray(data.sort_columns)
    ? (data.sort_columns as unknown[]).map(normalizeSortColumn)
    : []
  const limit = (data.limit as number | null | undefined) ?? null

  function setSortColumns(next: SortColumn[]) {
    onUpdate({ ...data, sort_columns: next })
  }

  function addColumn(field?: string) {
    setSortColumns([...sortColumns, { column: field ?? "", direction: "asc" }])
  }

  function removeColumn(i: number) {
    setSortColumns(sortColumns.filter((_, idx) => idx !== i))
  }

  function updateColumn(i: number, patch: Partial<SortColumn>) {
    setSortColumns(sortColumns.map((c, idx) => (idx === i ? { ...c, ...patch } : c)))
  }

  function moveColumn(i: number, delta: -1 | 1) {
    const next = [...sortColumns]
    const j = i + delta
    if (j < 0 || j >= next.length) return
    ;[next[i], next[j]] = [next[j], next[i]]
    setSortColumns(next)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) addColumn(field)
  }

  return (
    <div className="space-y-4">
      {/* Sort columns */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Ordenar por
        </label>

        <div className="space-y-2">
          {sortColumns.map((sc, i) => (
            <div
              key={i}
              className="rounded-lg border border-border bg-background p-2.5"
            >
              <div className="flex items-center gap-2">
                {/* Column name */}
                {upstreamFields.length > 0 ? (
                  <select
                    value={sc.column}
                    onChange={(e) => updateColumn(i, { column: e.target.value })}
                    className="h-7 flex-1 rounded-md border border-input bg-background px-2 text-xs text-foreground outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="">-- selecionar coluna --</option>
                    {upstreamFields.map((f) => (
                      <option key={f} value={f}>
                        {f}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={sc.column}
                    onChange={(e) => updateColumn(i, { column: e.target.value })}
                    placeholder="nome da coluna"
                    className="h-7 flex-1 rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                  />
                )}

                {/* Direction toggle */}
                <button
                  type="button"
                  onClick={() =>
                    updateColumn(i, {
                      direction: sc.direction === "asc" ? "desc" : "asc",
                    })
                  }
                  className={cn(
                    "flex h-7 items-center gap-1 rounded-md px-2 text-[11px] font-medium transition-colors",
                    sc.direction === "asc"
                      ? "bg-primary/10 text-primary"
                      : "bg-muted text-muted-foreground hover:text-foreground",
                  )}
                  title={sc.direction === "asc" ? "Crescente" : "Decrescente"}
                >
                  {sc.direction === "asc" ? (
                    <ArrowUp className="size-3" />
                  ) : (
                    <ArrowDown className="size-3" />
                  )}
                  {sc.direction === "asc" ? "ASC" : "DESC"}
                </button>

                {/* Move up/down */}
                <div className="flex flex-col">
                  <button
                    type="button"
                    onClick={() => moveColumn(i, -1)}
                    disabled={i === 0}
                    className="flex size-3.5 items-center justify-center text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
                  >
                    <ArrowUp className="size-3" />
                  </button>
                  <button
                    type="button"
                    onClick={() => moveColumn(i, 1)}
                    disabled={i === sortColumns.length - 1}
                    className="flex size-3.5 items-center justify-center text-muted-foreground transition-colors hover:text-foreground disabled:opacity-30"
                  >
                    <ArrowDown className="size-3" />
                  </button>
                </div>

                {/* Remove */}
                <button
                  type="button"
                  onClick={() => removeColumn(i)}
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Drop zone */}
        <div
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes("application/x-shift-field")) {
              e.preventDefault()
              e.dataTransfer.dropEffect = "copy"
            }
          }}
          onDrop={handleDrop}
          onClick={() => addColumn()}
          className={cn(
            "mt-2 flex w-full cursor-pointer items-center justify-center gap-2 rounded-lg border-2 border-dashed py-3 text-[11px] font-medium transition-all",
            "border-border text-muted-foreground hover:border-foreground/30 hover:text-foreground",
          )}
        >
          <span className="text-muted-foreground/50">Arraste campos aqui</span>
          <span className="text-muted-foreground/30">ou</span>
          <span className="flex items-center gap-1">
            <Plus className="size-3" />
            Adicionar coluna
          </span>
        </div>
      </div>

      {/* Limit */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Limite de linhas (opcional)
        </label>
        <input
          type="number"
          min={1}
          value={limit ?? ""}
          onChange={(e) => {
            const v = e.target.value ? parseInt(e.target.value, 10) : null
            onUpdate({ ...data, limit: v })
          }}
          placeholder="sem limite"
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
        <p className="text-[10px] text-muted-foreground/70">
          Quando informado, retorna apenas os N primeiros registros após a ordenação.
        </p>
      </div>
    </div>
  )
}
