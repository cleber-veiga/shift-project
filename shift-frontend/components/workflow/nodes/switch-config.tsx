"use client"

import { useCallback } from "react"
import { Plus, Trash2, X } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"

// ─── Types ────────────────────────────────────────────────────────────────────

interface SwitchCase {
  label: string
  values: string[]
}

interface SwitchConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

// ─── Component ────────────────────────────────────────────────────────────────

export function SwitchConfig({ data, onUpdate }: SwitchConfigProps) {
  const upstreamFields = useUpstreamFields()

  const switchField = (data.switch_field as string) ?? ""
  const cases: SwitchCase[] = Array.isArray(data.cases)
    ? (data.cases as SwitchCase[])
    : []

  const setCases = useCallback(
    (next: SwitchCase[]) => onUpdate({ ...data, cases: next }),
    [data, onUpdate],
  )

  function addCase() {
    setCases([...cases, { label: "", values: [""] }])
  }

  function removeCase(index: number) {
    setCases(cases.filter((_, i) => i !== index))
  }

  function updateCaseLabel(index: number, label: string) {
    setCases(
      cases.map((c, i) => (i === index ? { ...c, label } : c)),
    )
  }

  function addValueToCase(caseIndex: number) {
    setCases(
      cases.map((c, i) =>
        i === caseIndex ? { ...c, values: [...c.values, ""] } : c,
      ),
    )
  }

  function updateValue(caseIndex: number, valueIndex: number, value: string) {
    setCases(
      cases.map((c, i) =>
        i === caseIndex
          ? {
              ...c,
              values: c.values.map((v, vi) => (vi === valueIndex ? value : v)),
            }
          : c,
      ),
    )
  }

  function removeValue(caseIndex: number, valueIndex: number) {
    setCases(
      cases.map((c, i) =>
        i === caseIndex
          ? { ...c, values: c.values.filter((_, vi) => vi !== valueIndex) }
          : c,
      ),
    )
  }

  return (
    <div className="space-y-4">
      {/* Info banner */}
      <div className="rounded-lg border border-dashed border-orange-500/30 bg-orange-500/5 p-3">
        <p className="text-xs font-medium text-orange-600 dark:text-orange-400">Nó de Decisão (Switch)</p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Avalia o valor de um campo e distribui as linhas entre múltiplas saídas.
          Linhas que não casam com nenhum case vão para a saída <span className="font-semibold">default</span>.
        </p>
      </div>

      {/* Switch field */}
      <div className="space-y-1.5">
        <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Campo para avaliar
        </label>
        {upstreamFields.length > 0 ? (
          <select
            value={switchField}
            onChange={(e) => onUpdate({ ...data, switch_field: e.target.value })}
            className={cn(
              "h-8 w-full rounded-md border border-input bg-background px-2 text-xs outline-none focus:ring-1 focus:ring-primary",
              switchField ? "text-foreground" : "text-muted-foreground",
            )}
          >
            <option value="">Selecionar campo...</option>
            {upstreamFields.map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
        ) : (
          <input
            type="text"
            value={switchField}
            onChange={(e) => onUpdate({ ...data, switch_field: e.target.value })}
            placeholder="nome_do_campo"
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
        )}
      </div>

      {/* Cases */}
      <div>
        <label className="mb-2 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Cases (saídas)
        </label>

        <div className="space-y-3">
          {cases.map((c, ci) => (
            <div
              key={ci}
              className="rounded-lg border border-border bg-background p-3"
            >
              {/* Case header: label + delete */}
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={c.label}
                  onChange={(e) => updateCaseLabel(ci, e.target.value)}
                  placeholder="Nome da saída (ex: ativo, inativo)"
                  className="h-8 flex-1 rounded-md border border-input bg-background px-2.5 text-xs font-semibold text-foreground outline-none placeholder:text-muted-foreground placeholder:font-normal focus:ring-1 focus:ring-primary"
                />
                <button
                  type="button"
                  onClick={() => removeCase(ci)}
                  className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  aria-label="Remover case"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>

              {/* Values for this case */}
              <div className="mt-2 space-y-1.5">
                <label className="text-[10px] font-medium text-muted-foreground">
                  Valores que direcionam para esta saída:
                </label>
                {c.values.map((val, vi) => (
                  <div key={vi} className="flex items-center gap-1.5">
                    <input
                      type="text"
                      value={val}
                      onChange={(e) => updateValue(ci, vi, e.target.value)}
                      placeholder="Valor..."
                      className="h-7 flex-1 rounded border border-input bg-muted/30 px-2 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
                    />
                    {c.values.length > 1 && (
                      <button
                        type="button"
                        onClick={() => removeValue(ci, vi)}
                        className="flex size-6 shrink-0 items-center justify-center rounded text-muted-foreground/50 transition-colors hover:text-destructive"
                      >
                        <X className="size-3" />
                      </button>
                    )}
                  </div>
                ))}
                <button
                  type="button"
                  onClick={() => addValueToCase(ci)}
                  className="flex items-center gap-1 text-[10px] font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  <Plus className="size-3" />
                  Adicionar valor
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* Add case */}
        <button
          type="button"
          onClick={addCase}
          className="mt-2 flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border py-3 text-[11px] font-medium text-muted-foreground transition-all hover:border-foreground/30 hover:text-foreground"
        >
          <Plus className="size-3" />
          Adicionar case
        </button>
      </div>

      {/* Default info */}
      <div className="rounded-lg bg-muted/40 px-3 py-2">
        <p className="text-[10px] leading-relaxed text-muted-foreground">
          A saída <span className="font-semibold">default</span> é criada automaticamente e recebe
          todas as linhas que não casam com nenhum dos cases acima.
        </p>
      </div>
    </div>
  )
}
