"use client"

import { Plus, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields, useUpstreamOutputs } from "@/lib/workflow/upstream-fields-context"
import { FieldChipPicker } from "@/components/workflow/nodes/field-chip-picker"
import { HelpTip } from "@/components/ui/help-tip"

interface JoinCondition {
  left_column: string
  right_column: string
}

interface JoinConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

type JoinType = "inner" | "left" | "right" | "full"

const JOIN_TYPES: {
  value: JoinType
  label: string
  desc: string
  diagram: string
}[] = [
  {
    value: "inner",
    label: "Inner",
    desc: "Apenas linhas com correspondência nos dois lados",
    diagram: "🟢 ∩ 🟢",
  },
  {
    value: "left",
    label: "Left",
    desc: "Tudo da entrada esquerda; direita preenche quando casa",
    diagram: "🟢 ⫝ 🟡",
  },
  {
    value: "right",
    label: "Right",
    desc: "Tudo da entrada direita; esquerda preenche quando casa",
    diagram: "🟡 ⫝ 🟢",
  },
  {
    value: "full",
    label: "Full",
    desc: "Tudo dos dois lados; faltantes ficam NULL",
    diagram: "🟢 ∪ 🟢",
  },
]

function normalizeCondition(raw: unknown): JoinCondition {
  const c = (raw ?? {}) as Record<string, unknown>
  return {
    left_column: (c.left_column as string) ?? "",
    right_column: (c.right_column as string) ?? "",
  }
}

export function JoinConfig({ data, onUpdate }: JoinConfigProps) {
  const upstreamOutputs = useUpstreamOutputs()
  // O upstream "left" tem handle "left", o "right" tem "right". Os summaries
  // chegam na ordem dos edges; pegamos pelo handle se possível, com fallback
  // posicional (esquerda = primeiro, direita = segundo).
  const leftUpstream = upstreamOutputs[0]
  const rightUpstream = upstreamOutputs[1]
  const leftColumns = (leftUpstream?.output?.columns as string[] | undefined) ?? []
  const rightColumns = (rightUpstream?.output?.columns as string[] | undefined) ?? []
  // Fallback geral: ainda expor algo se schemas individuais não estão prontos.
  const fallbackColumns = useUpstreamFields()

  const joinType = (data.join_type as JoinType) ?? "inner"
  const conditions: JoinCondition[] = Array.isArray(data.conditions)
    ? (data.conditions as unknown[]).map(normalizeCondition)
    : []

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  function addCondition() {
    update({
      conditions: [...conditions, { left_column: "", right_column: "" }],
    })
  }

  function removeCondition(i: number) {
    update({ conditions: conditions.filter((_, idx) => idx !== i) })
  }

  function updateCondition(i: number, patch: Partial<JoinCondition>) {
    update({
      conditions: conditions.map((c, idx) =>
        idx === i ? { ...c, ...patch } : c,
      ),
    })
  }

  return (
    <div className="space-y-4">
      {/* Tipo de junção */}
      <div className="space-y-1.5">
        <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Tipo de junção
          <HelpTip>
            <strong>Inner:</strong> só linhas com correspondência dos dois lados.
            <br />
            <strong>Left:</strong> mantém todas da esquerda; quando não há
            correspondência na direita, as colunas da direita ficam NULL.
            <br />
            <strong>Right:</strong> espelho do Left.
            <br />
            <strong>Full:</strong> mantém tudo de ambos os lados; o que não
            casar fica NULL no lado oposto.
          </HelpTip>
        </label>
        <div className="grid grid-cols-2 gap-1">
          {JOIN_TYPES.map((t) => (
            <button
              key={t.value}
              type="button"
              onClick={() => update({ join_type: t.value })}
              title={t.desc}
              className={cn(
                "flex flex-col items-start gap-0.5 rounded-md px-3 py-2 text-left transition-colors",
                joinType === t.value
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground",
              )}
            >
              <span className="text-xs font-semibold">{t.label}</span>
              <span
                className={cn(
                  "text-[10px] leading-tight",
                  joinType === t.value
                    ? "text-primary-foreground/80"
                    : "text-muted-foreground/70",
                )}
              >
                {t.desc}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Aviso sobre as portas */}
      <div className="rounded-lg border border-dashed border-violet-500/30 bg-violet-500/5 p-3">
        <p className="text-xs font-medium text-violet-600 dark:text-violet-400">
          Conectar entradas
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Conecte um nó na porta <strong>left</strong> (esquerda) e outro na{" "}
          <strong>right</strong> (direita). A direção das portas determina os
          lados do JOIN.
        </p>
      </div>

      {/* Condições de junção */}
      <div>
        <label className="mb-2 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Chaves de junção
          <HelpTip>
            Cada par é uma comparação <code>left.coluna = right.coluna</code>{" "}
            usada na cláusula <code>ON</code>. Múltiplas linhas viram{" "}
            <code>AND</code> (todas precisam casar para a linha entrar no
            resultado).
          </HelpTip>
        </label>
        <p className="mb-2 text-[10px] text-muted-foreground/70">
          Os pares definem como as linhas se casam. Os nomes podem ser
          diferentes entre as duas entradas — ex.: <code>id</code> à esquerda
          casa com <code>cliente_id</code> à direita.
        </p>

        <div className="space-y-2">
          {conditions.map((c, i) => (
            <div
              key={i}
              className="rounded-lg border border-border bg-muted/20 p-2"
            >
              <div className="grid grid-cols-[1fr,auto,1fr,auto] items-center gap-2">
                <div className="min-w-0">
                  <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                    Esquerda{leftUpstream ? ` · ${leftUpstream.label}` : ""}
                  </p>
                  <FieldChipPicker
                    value={c.left_column}
                    onChange={(v) => updateCondition(i, { left_column: v })}
                    upstreamFields={
                      leftColumns.length > 0 ? leftColumns : fallbackColumns
                    }
                    placeholder="coluna da esquerda"
                  />
                </div>
                <span className="self-end pb-2 text-xs font-bold text-muted-foreground/50">
                  =
                </span>
                <div className="min-w-0">
                  <p className="mb-0.5 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/60">
                    Direita{rightUpstream ? ` · ${rightUpstream.label}` : ""}
                  </p>
                  <FieldChipPicker
                    value={c.right_column}
                    onChange={(v) => updateCondition(i, { right_column: v })}
                    upstreamFields={
                      rightColumns.length > 0 ? rightColumns : fallbackColumns
                    }
                    placeholder="coluna da direita"
                  />
                </div>
                <button
                  type="button"
                  onClick={() => removeCondition(i)}
                  className="flex size-7 shrink-0 items-center justify-center self-end rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                  aria-label="Remover par"
                >
                  <Trash2 className="size-3" />
                </button>
              </div>
            </div>
          ))}
        </div>

        <button
          type="button"
          onClick={addCondition}
          className="mt-2 flex w-full items-center justify-center gap-1 rounded-md border border-dashed border-border py-1.5 text-[11px] font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
        >
          <Plus className="size-3" />
          Adicionar par de chaves
        </button>

        {conditions.length === 0 && (
          <p className="mt-2 text-[10px] italic text-muted-foreground/70">
            Adicione pelo menos um par de colunas para o JOIN funcionar.
          </p>
        )}
      </div>
    </div>
  )
}
