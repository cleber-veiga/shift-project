"use client"

import { Plus, Trash2 } from "lucide-react"
import { cn } from "@/lib/utils"
import { useUpstreamFields } from "@/lib/workflow/upstream-fields-context"
import { FieldChipPicker } from "@/components/workflow/nodes/field-chip-picker"
import { HelpTip } from "@/components/ui/help-tip"

interface UnionConfigProps {
  data: Record<string, unknown>
  onUpdate: (data: Record<string, unknown>) => void
}

type DedupPriority = "first" | "last" | "input_first" | "input_last"

const DEDUP_PRIORITIES: { value: DedupPriority; label: string; desc: string }[] = [
  { value: "first",       label: "Primeira ocorrência",     desc: "Mantém a primeira linha vista (ordem natural)" },
  { value: "last",        label: "Última ocorrência",       desc: "Mantém a última linha vista" },
  { value: "input_first", label: "Da primeira entrada",     desc: "Em caso de empate, vence input_1 (depois input_2, etc.)" },
  { value: "input_last",  label: "Da última entrada",       desc: "Em caso de empate, vence a última entrada" },
]

export function UnionConfig({ data, onUpdate }: UnionConfigProps) {
  const upstreamFields = useUpstreamFields()

  const mode = (data.mode as string) ?? "by_name"
  const addSourceCol = (data.add_source_col as boolean) ?? false
  const sourceColName = (data.source_col_name as string) ?? "_source"
  const dedupKeys: string[] = Array.isArray(data.dedup_keys)
    ? (data.dedup_keys as string[])
    : []
  const dedupPriority = (data.dedup_priority as DedupPriority) ?? "first"
  const dedupEnabled = dedupKeys.length > 0

  function update(patch: Record<string, unknown>) {
    onUpdate({ ...data, ...patch })
  }

  // ── Dedup keys handlers ─────────────────────────────────────────────────
  function addDedupKey(field?: string) {
    if (field && dedupKeys.includes(field)) return
    update({ dedup_keys: [...dedupKeys, field ?? ""] })
  }
  function removeDedupKey(i: number) {
    update({ dedup_keys: dedupKeys.filter((_, idx) => idx !== i) })
  }
  function updateDedupKey(i: number, value: string) {
    update({
      dedup_keys: dedupKeys.map((k, idx) => (idx === i ? value : k)),
    })
  }
  function handleDedupDrop(e: React.DragEvent) {
    e.preventDefault()
    const f = e.dataTransfer.getData("application/x-shift-field")
    if (f) addDedupKey(f)
  }
  function toggleDedup() {
    if (dedupEnabled) {
      // Desligar: limpa as keys (mantém priority como ficou pra preservar UX
      // se o usuário ligar de novo).
      update({ dedup_keys: [] })
    } else {
      // Ligar: cria uma key vazia pra orientar o usuário a preencher.
      update({ dedup_keys: [""] })
    }
  }

  // input_first/input_last exigem ``mode === "by_name"`` no backend.
  const priorityNeedsByName = dedupPriority === "input_first" || dedupPriority === "input_last"
  const priorityIncompatible = priorityNeedsByName && mode !== "by_name"

  return (
    <div className="space-y-4">
      {/* Modo de alinhamento */}
      <div className="space-y-1.5">
        <label className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
          Modo de alinhamento
          <HelpTip>
            <strong>Por nome:</strong> empilha as linhas alinhando colunas
            pelo nome — o que faltar de um lado vira NULL. Recomendado em quase
            todos os casos.
            <br />
            <br />
            <strong>Por posição:</strong> empilha pela ordem das colunas. Os
            schemas precisam ser idênticos (mesma quantidade de colunas, mesma
            ordem). Useful quando você sabe que os dois arquivos têm exatamente
            o mesmo formato.
            <br />
            <br />
            Para combinar dados <em>com schemas diferentes mas que têm uma
            chave em comum</em>, use o nó <strong>Junção (Join)</strong> em
            vez deste.
          </HelpTip>
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

      {/* Aviso sobre as portas */}
      <div className="rounded-lg border border-dashed border-violet-500/30 bg-violet-500/5 p-3">
        <p className="text-xs font-medium text-violet-600 dark:text-violet-400">
          Conectar entradas
        </p>
        <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
          Conecte 2 ou mais nós usando as portas <strong>input_1</strong>,{" "}
          <strong>input_2</strong>, etc. O nó aceita quantas entradas forem
          necessárias.
        </p>
      </div>

      {/* Coluna de origem */}
      <div className="rounded-lg border border-border bg-card p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="text-xs font-semibold text-foreground">Coluna de origem</p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
              Adiciona uma coluna indicando de qual entrada veio cada linha
              (ex: &quot;input_1&quot;).
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

      {/* Dedup pós-união */}
      <div className="rounded-lg border border-border bg-card p-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
              Remover duplicatas após união
              <HelpTip>
                Quando ligado, aplica uma deduplicação na saída usando as
                colunas-chave. Se duas linhas tiverem o mesmo valor em todas
                as chaves, apenas uma sobrevive — escolhida pela{" "}
                <strong>prioridade</strong> abaixo.
                <br />
                <br />
                Útil quando as entradas podem ter o mesmo registro (ex.: o
                mesmo cliente apareceu em duas filiais) e você quer um único
                registro consolidado.
              </HelpTip>
            </p>
            <p className="mt-1 text-[11px] leading-relaxed text-muted-foreground">
              Aplica deduplicação pós-união por chave, com regra de prioridade.
            </p>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={dedupEnabled}
            onClick={toggleDedup}
            className={
              dedupEnabled
                ? "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-emerald-500 transition-colors"
                : "relative inline-flex h-5 w-9 shrink-0 items-center rounded-full bg-muted transition-colors"
            }
          >
            <span
              className={
                dedupEnabled
                  ? "inline-block size-4 translate-x-[18px] transform rounded-full bg-white shadow transition-transform"
                  : "inline-block size-4 translate-x-0.5 transform rounded-full bg-white shadow transition-transform"
              }
            />
          </button>
        </div>

        {dedupEnabled && (
          <div className="mt-3 space-y-3 border-t border-border pt-3">
            {/* Chaves */}
            <div>
              <label className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Chaves de duplicação
                <HelpTip>
                  Linhas que tiverem os mesmos valores em <strong>todas</strong>{" "}
                  estas colunas são consideradas duplicatas. Ex.: se a chave
                  for <code>cpf</code>, dois registros com o mesmo CPF viram
                  um só.
                </HelpTip>
              </label>
              <div className="space-y-1.5">
                {dedupKeys.map((key, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <div className="min-w-0 flex-1">
                      <FieldChipPicker
                        value={key}
                        onChange={(v) => updateDedupKey(i, v)}
                        upstreamFields={upstreamFields}
                        placeholder="coluna-chave"
                      />
                    </div>
                    <button
                      type="button"
                      onClick={() => removeDedupKey(i)}
                      className="flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-destructive/10 hover:text-destructive"
                      aria-label="Remover chave"
                    >
                      <Trash2 className="size-3" />
                    </button>
                  </div>
                ))}
              </div>
              <div
                onDragOver={(e) => {
                  if (!e.dataTransfer.types.includes("application/x-shift-field")) return
                  e.preventDefault()
                  e.dataTransfer.dropEffect = "copy"
                }}
                onDrop={handleDedupDrop}
                onClick={() => addDedupKey()}
                className="mt-1.5 flex w-full cursor-pointer items-center justify-center gap-1 rounded-md border border-dashed border-border py-1.5 text-[10px] font-medium text-muted-foreground transition-colors hover:border-foreground/30 hover:text-foreground"
              >
                <Plus className="size-3" />
                Adicionar chave
              </div>
            </div>

            {/* Prioridade */}
            <div>
              <label className="mb-1.5 flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">
                Em caso de duplicata, manter
                <HelpTip>
                  <strong>Primeira/última ocorrência:</strong> escolhe pela
                  ordem em que as linhas chegam (não-determinística sem ordenação
                  prévia, mas suficiente quando o critério não importa).
                  <br />
                  <br />
                  <strong>Da primeira/última entrada:</strong> usa a ordem das
                  portas — em <code>input_1</code> + <code>input_2</code>,
                  &quot;da primeira entrada&quot; mantém o registro de{" "}
                  <code>input_1</code> em caso de empate. Bom para definir
                  fonte canônica (ex.: ERP principal vence sobre filial).
                </HelpTip>
              </label>
              <div className="grid grid-cols-2 gap-1">
                {DEDUP_PRIORITIES.map((p) => (
                  <button
                    key={p.value}
                    type="button"
                    onClick={() => update({ dedup_priority: p.value })}
                    title={p.desc}
                    className={cn(
                      "flex flex-col items-start gap-0.5 rounded-md px-2.5 py-1.5 text-left transition-colors",
                      dedupPriority === p.value
                        ? "bg-primary text-primary-foreground"
                        : "bg-muted text-muted-foreground hover:text-foreground",
                    )}
                  >
                    <span className="text-[11px] font-semibold">{p.label}</span>
                    <span
                      className={cn(
                        "text-[9px] leading-tight",
                        dedupPriority === p.value
                          ? "text-primary-foreground/80"
                          : "text-muted-foreground/70",
                      )}
                    >
                      {p.desc}
                    </span>
                  </button>
                ))}
              </div>
              {priorityIncompatible && (
                <p className="mt-2 rounded-md border border-amber-500/30 bg-amber-500/5 px-2 py-1.5 text-[10px] text-amber-700 dark:text-amber-300">
                  Esta prioridade exige modo <strong>Por nome</strong>. Mude o
                  modo acima ou escolha &quot;primeira/última ocorrência&quot;.
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Cross-link pra Join */}
      <div className="rounded-lg border border-dashed border-border bg-muted/20 p-2.5">
        <p className="text-[10px] leading-relaxed text-muted-foreground">
          <strong className="text-foreground">Caso diferente?</strong> Se as
          entradas têm <em>schemas diferentes</em> mas se relacionam por uma
          chave em comum (ex.: pedidos × clientes pelo <code>cliente_id</code>),
          use o nó <strong>Junção (Join)</strong> em vez de União.
        </p>
      </div>
    </div>
  )
}
