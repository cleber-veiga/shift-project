"use client"

import { useCallback, useState } from "react"
import { ArrowRight, GripVertical, Plus, Sparkles, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"

// ─── Types ────────────────────────────────────────────────────────────────────

interface Mapping {
  source: string
  target: string
}

interface MapperConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ─── Component ────────────────────────────────────────────────────────────────

export function MapperConfig({ data, onUpdate }: MapperConfigProps) {
  const upstreamFields = useUpstreamFields()
  const [isDragOver, setIsDragOver] = useState(false)
  const [dragOverRowIdx, setDragOverRowIdx] = useState<number | null>(null)

  const mappings: Mapping[] = Array.isArray(data.mappings)
    ? (data.mappings as Mapping[])
    : []
  const dropUnmapped = Boolean(data.drop_unmapped)

  const setMappings = useCallback(
    (next: Mapping[]) => onUpdate({ ...data, mappings: next }),
    [data, onUpdate],
  )

  function addMapping() {
    setMappings([...mappings, { source: "", target: "" }])
  }

  function removeMapping(index: number) {
    setMappings(mappings.filter((_, i) => i !== index))
  }

  function updateMapping(index: number, field: "source" | "target", value: string) {
    setMappings(
      mappings.map((m, i) => (i === index ? { ...m, [field]: value } : m)),
    )
  }

  // When user selects a source field, auto-fill target with same name if empty
  function onSourceChange(index: number, value: string) {
    const current = mappings[index]
    const autoTarget = !current.target || current.target === current.source
    setMappings(
      mappings.map((m, i) =>
        i === index
          ? { ...m, source: value, target: autoTarget ? value : m.target }
          : m,
      ),
    )
  }

  function autoMapAll() {
    const existingSources = new Set(mappings.map((m) => m.source))
    const newMappings = upstreamFields
      .filter((f) => !existingSources.has(f))
      .map((f) => ({ source: f, target: f }))
    setMappings([...mappings, ...newMappings])
  }

  // ─── Drag & Drop handlers ──────────────────────────────────────────────────

  function handleDropOnZone(e: React.DragEvent) {
    e.preventDefault()
    setIsDragOver(false)
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (!field) return

    // Don't add duplicates
    const exists = mappings.some((m) => m.source === field)
    if (!exists) {
      setMappings([...mappings, { source: field, target: field }])
    }
  }

  function handleDropOnRow(e: React.DragEvent, index: number) {
    e.preventDefault()
    e.stopPropagation()
    setDragOverRowIdx(null)
    const field = e.dataTransfer.getData("application/x-shift-field")
    if (!field) return

    const current = mappings[index]
    const autoTarget = !current.target || current.target === current.source
    setMappings(
      mappings.map((m, i) =>
        i === index
          ? { ...m, source: field, target: autoTarget ? field : m.target }
          : m,
      ),
    )
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

  // Fields already used in other mapping rows
  const usedSources = new Set(mappings.map((m) => m.source))

  return (
    <div className="space-y-4">
      {/* Label */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Nome do nó
        </label>
        <input
          type="text"
          value={(data.label as string) ?? ""}
          onChange={(e) => onUpdate({ ...data, label: e.target.value })}
          placeholder="Nome personalizado..."
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
      </div>

      {/* Drop unmapped toggle */}
      <label className="flex items-center gap-2">
        <input
          type="checkbox"
          checked={dropUnmapped}
          onChange={(e) => onUpdate({ ...data, drop_unmapped: e.target.checked })}
          className="size-3.5 rounded border-input accent-primary"
        />
        <span className="text-xs text-foreground">Remover campos não mapeados</span>
      </label>

      {/* Mappings section */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Mapeamentos
          </label>
          {upstreamFields.length > 0 && mappings.length < upstreamFields.length && (
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

        {/* Column headers */}
        {mappings.length > 0 && (
          <div className="mb-1.5 grid grid-cols-[1fr_20px_1fr_28px] items-center gap-1.5 px-0.5">
            <span className="text-[10px] font-medium text-muted-foreground">Campo origem</span>
            <span />
            <span className="text-[10px] font-medium text-muted-foreground">Campo destino</span>
            <span />
          </div>
        )}

        {/* Mapping rows */}
        <div className="space-y-1.5">
          {mappings.map((m, i) => (
            <div
              key={i}
              className={cn(
                "grid grid-cols-[1fr_20px_1fr_28px] items-center gap-1.5 rounded-md transition-colors",
                dragOverRowIdx === i && "bg-primary/5 ring-1 ring-primary/30",
              )}
              onDragOver={(e) => handleDragOverRow(e, i)}
              onDragLeave={() => setDragOverRowIdx(null)}
              onDrop={(e) => handleDropOnRow(e, i)}
            >
              {/* Source */}
              {upstreamFields.length > 0 ? (
                <select
                  value={m.source}
                  onChange={(e) => onSourceChange(i, e.target.value)}
                  className={cn(
                    "h-8 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary",
                    m.source ? "text-foreground" : "text-muted-foreground",
                  )}
                >
                  <option value="">Selecionar...</option>
                  {upstreamFields.map((f) => (
                    <option
                      key={f}
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
                  value={m.source}
                  onChange={(e) => updateMapping(i, "source", e.target.value)}
                  placeholder="campo_origem"
                  className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                />
              )}

              {/* Arrow */}
              <div className="flex items-center justify-center">
                <ArrowRight className="size-3.5 text-muted-foreground/50" />
              </div>

              {/* Target */}
              <input
                type="text"
                value={m.target}
                onChange={(e) => updateMapping(i, "target", e.target.value)}
                placeholder="campo_destino"
                className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
              />

              {/* Delete */}
              <button
                type="button"
                onClick={() => removeMapping(i)}
                className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                aria-label="Remover mapeamento"
              >
                <Trash2 className="size-3" />
              </button>
            </div>
          ))}
        </div>

        {/* Drop zone + Add button */}
        <div
          onDragOver={handleDragOverZone}
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
              <span className="text-muted-foreground/50">
                Arraste campos da entrada aqui
              </span>
              <span className="text-muted-foreground/30">ou</span>
              <span className="flex items-center gap-1">
                <Plus className="size-3" />
                Adicionar campo
              </span>
            </>
          )}
        </div>

        {/* Hint when no upstream fields */}
        {upstreamFields.length === 0 && mappings.length === 0 && (
          <p className="mt-2 text-[10px] leading-relaxed text-muted-foreground/70">
            Execute o nó anterior para ver os campos disponíveis automaticamente,
            ou adicione mapeamentos manualmente.
          </p>
        )}
      </div>
    </div>
  )
}
