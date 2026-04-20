"use client"

import { useCallback, useState } from "react"
import { GripVertical, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"

interface DeduplicationConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

export function DeduplicationConfig({ data, onUpdate }: DeduplicationConfigProps) {
  const upstreamFields = useUpstreamFields()
  const [isDragOverKeys, setIsDragOverKeys] = useState(false)

  const partitionBy: string[] = Array.isArray(data.partition_by)
    ? (data.partition_by as string[])
    : []
  const orderBy = typeof data.order_by === "string" ? (data.order_by as string) : ""
  const keep = (data.keep as string) === "last" ? "last" : "first"

  const setPartitionBy = useCallback(
    (next: string[]) => onUpdate({ ...data, partition_by: next }),
    [data, onUpdate],
  )

  function addKey(field: string) {
    if (!field || partitionBy.includes(field)) return
    setPartitionBy([...partitionBy, field])
  }

  function removeKey(field: string) {
    setPartitionBy(partitionBy.filter((f) => f !== field))
  }

  function handleDropOnKeys(e: React.DragEvent) {
    e.preventDefault()
    setIsDragOverKeys(false)
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (field) addKey(field)
  }

  function handleDragOverKeys(e: React.DragEvent) {
    e.preventDefault()
    e.dataTransfer.dropEffect = "copy"
    setIsDragOverKeys(true)
  }

  const availableFields = upstreamFields.filter((f) => !partitionBy.includes(f))

  return (
    <div className="space-y-5">
      {/* ── Chave de duplicidade ─────────────────────────────────────────── */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Chave de duplicidade
        </label>

        <div
          onDragOver={handleDragOverKeys}
          onDragLeave={() => setIsDragOverKeys(false)}
          onDrop={handleDropOnKeys}
          className={cn(
            "min-h-[60px] rounded-lg border-2 border-dashed p-2 transition-colors",
            isDragOverKeys
              ? "border-primary bg-primary/5"
              : partitionBy.length > 0
                ? "border-border bg-background"
                : "border-border",
          )}
        >
          {partitionBy.length === 0 ? (
            <div className="flex h-full min-h-[44px] items-center justify-center gap-2 text-[11px] text-muted-foreground">
              {isDragOverKeys ? (
                <>
                  <GripVertical className="size-3.5" />
                  Soltar campo aqui
                </>
              ) : (
                <span className="text-muted-foreground/60">
                  Arraste colunas do Schema ou adicione abaixo
                </span>
              )}
            </div>
          ) : (
            <div className="flex flex-wrap gap-1.5">
              {partitionBy.map((field) => (
                <span
                  key={field}
                  className="inline-flex items-center gap-1 rounded-md bg-primary/10 px-2 py-1 text-[11px] font-medium text-primary"
                >
                  {field}
                  <button
                    type="button"
                    onClick={() => removeKey(field)}
                    className="rounded text-primary/70 hover:text-primary"
                    aria-label={`Remover ${field}`}
                  >
                    <X className="size-3" />
                  </button>
                </span>
              ))}
            </div>
          )}
        </div>

        {/* Picker para adicionar via dropdown quando há fields disponíveis */}
        {availableFields.length > 0 && (
          <div className="mt-2 flex items-center gap-2">
            <select
              value=""
              onChange={(e) => {
                if (e.target.value) addKey(e.target.value)
              }}
              className="h-8 flex-1 rounded-md border border-input bg-background px-2 text-xs text-muted-foreground outline-none focus:ring-1 focus:ring-primary"
            >
              <option value="">+ Adicionar coluna…</option>
              {availableFields.map((f) => (
                <option key={f} value={f}>
                  {f}
                </option>
              ))}
            </select>
          </div>
        )}

        {upstreamFields.length === 0 && partitionBy.length === 0 && (
          <input
            type="text"
            placeholder="nome_da_coluna"
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault()
                const value = (e.target as HTMLInputElement).value.trim()
                if (value) {
                  addKey(value)
                  ;(e.target as HTMLInputElement).value = ""
                }
              }
            }}
            className="mt-2 h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
        )}

        <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground/70">
          Linhas com a mesma combinação desses valores serão consideradas duplicadas.
        </p>
      </div>

      {/* ── Desempate (opcional) ─────────────────────────────────────────── */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Desempate (opcional)
        </label>

        <div className="space-y-2">
          <div className="flex items-center gap-2">
            <span className="w-20 shrink-0 text-[11px] text-muted-foreground">
              Coluna
            </span>
            {upstreamFields.length > 0 ? (
              <select
                value={orderBy}
                onChange={(e) => onUpdate({ ...data, order_by: e.target.value })}
                className={cn(
                  "h-8 flex-1 rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary",
                  orderBy ? "text-foreground" : "text-muted-foreground",
                )}
              >
                <option value="">— qualquer linha do grupo —</option>
                {upstreamFields.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            ) : (
              <input
                type="text"
                value={orderBy}
                onChange={(e) => onUpdate({ ...data, order_by: e.target.value })}
                placeholder="coluna_de_ordenacao (opcional)"
                className="h-8 flex-1 rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
              />
            )}
          </div>

          {orderBy && (
            <div className="flex items-center gap-2">
              <span className="w-20 shrink-0 text-[11px] text-muted-foreground">
                Manter
              </span>
              <div className="flex flex-1 gap-1">
                <button
                  type="button"
                  onClick={() => onUpdate({ ...data, keep: "first" })}
                  className={cn(
                    "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    keep === "first"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:text-foreground",
                  )}
                >
                  Primeiro (ASC)
                </button>
                <button
                  type="button"
                  onClick={() => onUpdate({ ...data, keep: "last" })}
                  className={cn(
                    "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                    keep === "last"
                      ? "bg-primary text-primary-foreground"
                      : "bg-muted text-muted-foreground hover:text-foreground",
                  )}
                >
                  Último (DESC)
                </button>
              </div>
            </div>
          )}
        </div>

        <p className="mt-1.5 text-[10px] leading-relaxed text-muted-foreground/70">
          {orderBy
            ? `Mantém a linha com ${keep === "first" ? "menor" : "maior"} valor de "${orderBy}" em cada grupo.`
            : "Sem coluna de desempate, qualquer linha do grupo é mantida."}
        </p>
      </div>
    </div>
  )
}

