"use client"

import { cn } from "@/lib/utils"

interface UnionConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

export function UnionConfig({ data, onUpdate }: UnionConfigProps) {
  const mode = (data.mode as string) ?? "by_name"
  const addSourceCol = (data.add_source_col as boolean) ?? false
  const sourceColName = (data.source_col_name as string) ?? "_source"

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  return (
    <div className="space-y-4">
      {/* Mode */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Modo de alinhamento
        </label>
        <div className="flex gap-1">
          <button
            type="button"
            onClick={() => update({ mode: "by_name" })}
            className={cn(
              "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              mode === "by_name"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            Por nome
          </button>
          <button
            type="button"
            onClick={() => update({ mode: "by_position" })}
            className={cn(
              "flex-1 rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
              mode === "by_position"
                ? "bg-primary text-primary-foreground"
                : "bg-muted text-muted-foreground hover:text-foreground",
            )}
          >
            Por posição
          </button>
        </div>
        <p className="text-[10px] text-muted-foreground/70">
          {mode === "by_name"
            ? "Alinha colunas pelo nome — colunas ausentes ficam NULL. Recomendado quando os schemas diferem."
            : "Alinha colunas pela posição — os schemas devem ser compatíveis."}
        </p>
      </div>

      {/* Informational note about inputs */}
      <div className="rounded-lg border border-dashed border-violet-500/30 bg-violet-500/5 p-3">
        <p className="text-xs font-medium text-violet-600 dark:text-violet-400">
          Conectar entradas
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Conecte 2 ou mais nós usando as portas <strong>input_1</strong>, <strong>input_2</strong>,
          etc. O nó aceita quantas entradas forem necessárias.
        </p>
      </div>

      {/* Source column */}
      <div className="rounded-lg border border-border bg-card p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-foreground">Coluna de origem</p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
              Adiciona uma coluna indicando de qual entrada veio cada linha (ex: &quot;input_1&quot;).
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={addSourceCol}
            onClick={() => update({ add_source_col: !addSourceCol })}
            className={
              addSourceCol
                ? "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-emerald-500 transition-colors"
                : "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-muted transition-colors"
            }
          >
            <span
              className={
                addSourceCol
                  ? "inline-block size-4 translate-x-[18px] transform rounded-full bg-white shadow transition-transform"
                  : "inline-block size-4 translate-x-0.5 transform rounded-full bg-white shadow transition-transform"
              }
            />
          </button>
        </div>

        {addSourceCol && (
          <div className="mt-3 space-y-1.5">
            <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
              Nome da coluna
            </label>
            <input
              type="text"
              value={sourceColName}
              onChange={(e) => update({ source_col_name: e.target.value || "_source" })}
              placeholder="_source"
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
            />
          </div>
        )}
      </div>
    </div>
  )
}
