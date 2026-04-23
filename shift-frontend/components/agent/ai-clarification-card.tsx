"use client"

import { useMemo, useState } from "react"
import { Check, HelpCircle, Sparkles } from "lucide-react"
import { cn } from "@/lib/utils"
import type {
  ClarificationOption,
  ClarificationPayload,
} from "@/lib/types/ai-panel"
import { MorphLoader } from "@/components/ui/morph-loader"

/**
 * Card renderizado quando o Platform Agent pede um dado que so o usuario
 * pode informar (ex: conexao alvo, tipo de trigger). Em vez de exibir o
 * texto longo com as opcoes numeradas, apresentamos chips clicaveis que
 * disparam `onSelect` com o label escolhido — que sera enviado como
 * mensagem de usuario pelo pipeline normal do chat.
 *
 * Fica disabled depois que o usuario responde (evita double-click e deixa
 * claro, ao rolar a conversa, qual foi a escolha).
 */
export interface ClarificationSelection {
  option: ClarificationOption
  field: ClarificationPayload["field"]
  question: string
  /** true quando o usuario escolheu o extra_option (fora do catalogo). */
  isExtra: boolean
}

interface AIClarificationCardProps {
  question: string
  clarification: ClarificationPayload
  status: "pending" | "answered"
  answer?: string
  onSelect?: (selection: ClarificationSelection) => void
  disabled?: boolean
}

const FIELD_LABEL: Record<ClarificationPayload["field"], string> = {
  connection_id: "Escolha a conexao",
  trigger_type: "Como este fluxo sera disparado?",
  workflow_id: "Selecione o workflow",
  target_table: "Selecione a tabela",
  other: "Preciso de mais informacao",
}

export function AIClarificationCard({
  question,
  clarification,
  status,
  answer,
  onSelect,
  disabled,
}: AIClarificationCardProps) {
  const [hovered, setHovered] = useState<string | null>(null)
  const [pending, setPending] = useState<string | null>(null)

  const headerLabel = useMemo(
    () => FIELD_LABEL[clarification.field] ?? "Preciso de mais informacao",
    [clarification.field],
  )

  const isAnswered = status === "answered"
  const isLocked = isAnswered || Boolean(disabled)

  const handleClick = (opt: ClarificationOption, isExtra: boolean) => {
    if (isLocked || pending) return
    setPending(opt.value)
    try {
      onSelect?.({
        option: opt,
        field: clarification.field,
        question: clarification.question || question,
        isExtra,
      })
    } finally {
      // Nao precisamos limpar pending — o proximo render vem com
      // status="answered" via reducer.
    }
  }

  const renderOption = (opt: ClarificationOption, emphasis?: "extra") => {
    const isSelected =
      isAnswered && (answer === opt.label || answer === opt.value)
    const isPending = pending === opt.value && !isAnswered
    const isHover = hovered === opt.value

    return (
      <button
        key={opt.value}
        type="button"
        onClick={() => handleClick(opt, emphasis === "extra")}
        onMouseEnter={() => setHovered(opt.value)}
        onMouseLeave={() => setHovered(null)}
        disabled={isLocked || Boolean(pending)}
        className={cn(
          "group relative flex w-full items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left transition",
          "disabled:cursor-not-allowed",
          isSelected
            ? "border-primary/60 bg-primary/10 ring-1 ring-primary/30"
            : isLocked
              ? "border-border/60 bg-background/40 opacity-60"
              : emphasis === "extra"
                ? "border-dashed border-border bg-background/50 hover:border-primary/40 hover:bg-primary/5"
                : "border-border bg-background/70 hover:border-primary/40 hover:bg-primary/5",
        )}
      >
        <div
          className={cn(
            "mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border transition",
            isSelected
              ? "border-primary bg-primary text-primary-foreground"
              : isHover && !isLocked
                ? "border-primary/60 bg-primary/10"
                : "border-border bg-background",
          )}
          aria-hidden
        >
          {isSelected ? (
            <Check className="size-2.5" strokeWidth={3} />
          ) : isPending ? (
            <MorphLoader className="size-2.5" />
          ) : emphasis === "extra" ? (
            <Sparkles className="size-2.5 text-primary/70" />
          ) : null}
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <span
            className={cn(
              "text-xs font-medium leading-snug",
              isSelected ? "text-foreground" : "text-foreground",
            )}
          >
            {opt.label}
          </span>
          {opt.hint ? (
            <span className="mt-0.5 text-[10px] leading-snug text-muted-foreground">
              {opt.hint}
            </span>
          ) : null}
        </div>
      </button>
    )
  }

  return (
    <div className="overflow-hidden rounded-xl border border-sky-400/30 bg-sky-500/[0.04]">
      {/* Cabecalho */}
      <div className="flex items-center gap-2 border-b border-sky-400/20 bg-sky-500/[0.06] px-3 py-2">
        <HelpCircle className="size-3.5 shrink-0 text-sky-500 dark:text-sky-400" />
        <span className="text-xs font-semibold text-foreground">{headerLabel}</span>
        {isAnswered ? (
          <span className="ml-auto flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
            <Check className="size-3" /> Respondido
          </span>
        ) : (
          <span className="ml-auto rounded-full bg-sky-500/15 px-2 py-0.5 text-[10px] font-semibold text-sky-600 dark:text-sky-400">
            Aguardando escolha
          </span>
        )}
      </div>

      <div className="space-y-2.5 p-3">
        {question ? (
          <p className="text-xs leading-relaxed text-foreground">{question}</p>
        ) : null}

        <div className="flex flex-col gap-1.5">
          {clarification.options.map((opt) => renderOption(opt))}
          {clarification.extraOption
            ? renderOption(clarification.extraOption, "extra")
            : null}
        </div>

        {isAnswered && answer ? (
          <p className="text-[10px] text-muted-foreground">
            <span className="font-semibold">Sua escolha:</span> {answer}
          </p>
        ) : null}
      </div>
    </div>
  )
}
