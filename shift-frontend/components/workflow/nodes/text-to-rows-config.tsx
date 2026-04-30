"use client"

import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import { FieldChipPicker } from "@/components/workflow/nodes/field-chip-picker"

interface TextToRowsConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

export function TextToRowsConfig({ data, onUpdate }: TextToRowsConfigProps) {
  const upstreamFields = useUpstreamFields()

  const columnToSplit = (data.column_to_split as string) ?? ""
  const delimiter = (data.delimiter as string) ?? ","
  const outputColumn = (data.output_column as string | null) ?? null
  const keepEmpty = (data.keep_empty as boolean) ?? false
  const trimValues = (data.trim_values as boolean) ?? true
  const maxOutputRows = (data.max_output_rows as number | null) ?? null

  return (
    <div className="space-y-4">
      {/* Column to split */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Coluna a dividir
        </label>
        <FieldChipPicker
          value={columnToSplit}
          onChange={(v) => onUpdate({ ...data, column_to_split: v })}
          upstreamFields={upstreamFields}
          placeholder="selecionar coluna"
        />
      </div>

      {/* Delimiter */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Delimitador
        </label>
        <input
          type="text"
          value={delimiter}
          onChange={(e) => onUpdate({ ...data, delimiter: e.target.value })}
          placeholder=","
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
        <p className="text-[10px] text-muted-foreground/70">
          Suporta múltiplos caracteres, ex.: <code className="font-mono">||</code>
        </p>
      </div>

      {/* Output column (optional rename) */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Nome da coluna de saída (opcional)
        </label>
        <input
          type="text"
          value={outputColumn ?? ""}
          onChange={(e) =>
            onUpdate({ ...data, output_column: e.target.value || null })
          }
          placeholder={columnToSplit || "mesma da entrada"}
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
        <p className="text-[10px] text-muted-foreground/70">
          Vazio = usa o mesmo nome da coluna de entrada.
        </p>
      </div>

      {/* Options */}
      <div className="space-y-2">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Opções
        </label>

        <label className="flex cursor-pointer items-center gap-2.5">
          <div
            role="checkbox"
            aria-checked={trimValues}
            tabIndex={0}
            onClick={() => onUpdate({ ...data, trim_values: !trimValues })}
            onKeyDown={(e) => {
              if (e.key === " " || e.key === "Enter")
                onUpdate({ ...data, trim_values: !trimValues })
            }}
            className={cn(
              "flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded border transition-colors",
              trimValues
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input bg-background",
            )}
          >
            {trimValues && (
              <svg className="size-2.5" viewBox="0 0 10 10" fill="none">
                <path
                  d="M2 5l2.5 2.5L8 3"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </div>
          <span className="text-xs text-foreground">
            Remover espaços (trim)
          </span>
        </label>

        <label className="flex cursor-pointer items-center gap-2.5">
          <div
            role="checkbox"
            aria-checked={keepEmpty}
            tabIndex={0}
            onClick={() => onUpdate({ ...data, keep_empty: !keepEmpty })}
            onKeyDown={(e) => {
              if (e.key === " " || e.key === "Enter")
                onUpdate({ ...data, keep_empty: !keepEmpty })
            }}
            className={cn(
              "flex h-4 w-4 shrink-0 cursor-pointer items-center justify-center rounded border transition-colors",
              keepEmpty
                ? "border-primary bg-primary text-primary-foreground"
                : "border-input bg-background",
            )}
          >
            {keepEmpty && (
              <svg className="size-2.5" viewBox="0 0 10 10" fill="none">
                <path
                  d="M2 5l2.5 2.5L8 3"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            )}
          </div>
          <span className="text-xs text-foreground">
            Manter partes vazias
          </span>
        </label>
      </div>

      {/* Max output rows */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Limite de linhas de saída (opcional)
        </label>
        <input
          type="number"
          min={1}
          value={maxOutputRows ?? ""}
          onChange={(e) => {
            const v = e.target.value ? parseInt(e.target.value, 10) : null
            onUpdate({ ...data, max_output_rows: v })
          }}
          placeholder="sem limite"
          className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
        />
        <p className="text-[10px] text-muted-foreground/70">
          Limita o total de linhas geradas após a explosão.
        </p>
      </div>
    </div>
  )
}
