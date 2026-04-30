"use client"

import { cn } from "@/lib/utils"
import { HelpTip } from "@/components/ui/help-tip"

interface SampleConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

const MODES = [
  { value: "first_n", label: "Primeiras N linhas" },
  { value: "random", label: "Aleatória (com seed)" },
  { value: "percent", label: "Percentual" },
] as const

type SampleMode = "first_n" | "random" | "percent"

export function SampleConfig({ data, onUpdate }: SampleConfigProps) {
  const mode = (data.mode as SampleMode) ?? "first_n"
  const n = (data.n as number | null | undefined) ?? null
  const seed = (data.seed as number | undefined) ?? 42
  const percent = (data.percent as number | null | undefined) ?? null

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  return (
    <div className="space-y-4">
      {/* Mode selector */}
      <div className="space-y-1.5">
        <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Modo
          <HelpTip>
            <strong>Primeiras N linhas:</strong> retorna sempre as N primeiras
            do dataset, na ordem em que vieram.<br />
            <br />
            <strong>Aleatória (com seed):</strong> sorteia N linhas. Usar o
            mesmo seed garante o mesmo sorteio em execuções diferentes — útil
            para depurar e produzir relatórios reproduzíveis.<br />
            <br />
            <strong>Percentual:</strong> mantém X% das linhas via sorteio
            probabilístico. Bom para amostrar datasets grandes mantendo a
            proporção, mas o resultado pode variar levemente entre execuções.
          </HelpTip>
        </label>
        <div className="flex flex-col gap-1">
          {MODES.map((m) => (
            <button
              key={m.value}
              type="button"
              onClick={() => update({ mode: m.value })}
              className={cn(
                "w-full rounded-md px-3 py-2 text-left text-xs font-medium transition-colors",
                mode === m.value
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:text-foreground",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      {/* N field (first_n and random) */}
      {(mode === "first_n" || mode === "random") && (
        <div className="space-y-1.5">
          <label className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            {mode === "first_n" ? "Quantidade de linhas" : "Quantidade de linhas (N)"}
          </label>
          <input
            type="number"
            min={0}
            value={n ?? ""}
            onChange={(e) => update({ n: e.target.value ? parseInt(e.target.value, 10) : null })}
            placeholder="ex: 1000"
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
        </div>
      )}

      {/* Seed field (random only) */}
      {mode === "random" && (
        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Seed (reprodutibilidade)
            <HelpTip>
              O <strong>seed</strong> é uma "semente" numérica usada pelo
              sorteador aleatório. Como o computador gera "aleatórios" a partir
              dessa semente, fixar o número faz com que o mesmo conjunto de
              linhas seja sempre escolhido — mesma execução, mesma amostra.
              <br />
              <br />
              <strong>Quando manter o mesmo:</strong> ao depurar um fluxo,
              comparar resultados entre execuções, ou produzir relatórios
              reproduzíveis.<br />
              <strong>Quando trocar:</strong> quando quiser uma amostra
              diferente (qualquer outro número serve).
            </HelpTip>
          </label>
          <input
            type="number"
            min={0}
            value={seed}
            onChange={(e) => update({ seed: parseInt(e.target.value, 10) || 42 })}
            className="h-8 w-full rounded-md border border-input bg-background px-2.5 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
          />
          <p className="text-[10px] text-muted-foreground/70">
            Mesmo seed garante a mesma amostra em execuções diferentes.
          </p>
        </div>
      )}

      {/* Percent field */}
      {mode === "percent" && (
        <div className="space-y-1.5">
          <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
            Percentual (%)
            <HelpTip>
              Cada linha do dataset tem essa probabilidade (em %) de entrar na
              amostra. Por isso o número final pode variar levemente entre
              execuções — um dataset de 1.000 linhas com 10% pode retornar 98
              ou 105, por exemplo.<br />
              <br />
              Use quando o tamanho exato não importa, mas você quer manter a
              proporção do dataset. Para um número fixo, use{" "}
              <em>Aleatória (com seed)</em>.
            </HelpTip>
          </label>
          <div className="relative">
            <input
              type="number"
              min={0.01}
              max={100}
              step={0.1}
              value={percent ?? ""}
              onChange={(e) =>
                update({ percent: e.target.value ? parseFloat(e.target.value) : null })
              }
              placeholder="ex: 10"
              className="h-8 w-full rounded-md border border-input bg-background px-2.5 pr-8 text-xs text-foreground outline-none placeholder:text-muted-foreground focus:ring-1 focus:ring-primary"
            />
            <span className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
              %
            </span>
          </div>
          <p className="text-[10px] text-muted-foreground/70">
            Amostragem probabilística — o resultado pode variar levemente entre execuções.
          </p>
        </div>
      )}
    </div>
  )
}
