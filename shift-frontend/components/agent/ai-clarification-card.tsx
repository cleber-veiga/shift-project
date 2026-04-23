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
 * Caso especial: quando o usuario escolhe o extra_option do
 * field=connection_id ("Criar variavel de conexao"), abrimos um formulario
 * INLINE no proprio card para capturar nome da variavel + connection_type
 * antes de enviar. Isso evita o pingue-pongue de turnos texto-livre em que
 * o planner perde o contexto e reinterpreta o nome da variavel como
 * "renomear conexao existente".
 */
export interface ClarificationSelection {
  option: ClarificationOption
  field: ClarificationPayload["field"]
  question: string
  /** true quando o usuario escolheu o extra_option (fora do catalogo). */
  isExtra: boolean
  /**
   * Dados coletados no formulario inline (so preenche quando o usuario
   * escolheu "Criar variavel de conexao" e submeteu o form).
   */
  connectionVariable?: {
    name: string
    connectionType: ConnectionType
  }
}

type ConnectionType = "oracle" | "sqlserver" | "postgres" | "firebird" | "mysql" | "mongodb"

const CONNECTION_TYPE_OPTIONS: Array<{ value: ConnectionType; label: string }> = [
  { value: "oracle", label: "Oracle" },
  { value: "sqlserver", label: "SQL Server" },
  { value: "postgres", label: "PostgreSQL" },
  { value: "firebird", label: "Firebird" },
  { value: "mysql", label: "MySQL" },
  { value: "mongodb", label: "MongoDB" },
]

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
  // Form inline para o caminho "criar variavel de conexao".
  const [formOpen, setFormOpen] = useState(false)
  const [varName, setVarName] = useState("")
  const [varType, setVarType] = useState<ConnectionType>("oracle")
  const [varNameError, setVarNameError] = useState<string | null>(null)

  const headerLabel = useMemo(
    () => FIELD_LABEL[clarification.field] ?? "Preciso de mais informacao",
    [clarification.field],
  )

  const isAnswered = status === "answered"
  const isLocked = isAnswered || Boolean(disabled)
  // O extra_option de connection_id precisa de dois dados extras (nome +
  // connection_type). Em vez de confiar no LLM para extrair isso de texto
  // livre no proximo turno, abrimos um mini-form no card.
  const extraRequiresForm =
    clarification.field === "connection_id" &&
    Boolean(clarification.extraOption)

  const handleClick = (opt: ClarificationOption, isExtra: boolean) => {
    if (isLocked || pending) return
    if (isExtra && extraRequiresForm) {
      setFormOpen(true)
      setVarNameError(null)
      return
    }
    setPending(opt.value)
    onSelect?.({
      option: opt,
      field: clarification.field,
      question: clarification.question || question,
      isExtra,
    })
  }

  const handleSubmitForm = () => {
    if (!clarification.extraOption || isLocked || pending) return
    const name = varName.trim()
    // Identificador valido para referenciar via {{vars.NOME}} no config
    // dos nos: so letras/numeros/underscore, nao inicia com digito.
    if (!name || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(name)) {
      setVarNameError(
        "Use letras, numeros e underscore. Nao pode comecar com numero.",
      )
      return
    }
    setVarNameError(null)
    setPending(clarification.extraOption.value)
    onSelect?.({
      option: clarification.extraOption,
      field: clarification.field,
      question: clarification.question || question,
      isExtra: true,
      connectionVariable: { name, connectionType: varType },
    })
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
        disabled={isLocked || Boolean(pending) || formOpen}
        className={cn(
          "group relative flex w-full items-start gap-2.5 rounded-xl border px-3 py-2.5 text-left transition",
          "disabled:cursor-not-allowed",
          isSelected
            ? "border-primary/60 bg-primary/10 ring-1 ring-primary/30"
            : isLocked || formOpen
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
              : isHover && !isLocked && !formOpen
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
          <span className="text-xs font-medium leading-snug text-foreground">
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

        {formOpen && clarification.extraOption && !isAnswered ? (
          <div className="rounded-xl border border-primary/30 bg-primary/[0.04] p-3 space-y-2.5">
            <div className="flex items-start gap-2">
              <Sparkles className="mt-0.5 size-3 shrink-0 text-primary/80" />
              <div className="text-[11px] leading-snug text-foreground">
                <p className="font-semibold">Variavel de conexao</p>
                <p className="text-muted-foreground">
                  Essa variavel sera declarada no workflow e usada como
                  <code className="mx-1 rounded bg-muted px-1 py-0.5 font-mono text-[10px]">{"{{vars.NOME}}"}</code>
                  no connection_id dos nos. O valor real e informado no
                  momento da execucao.
                </p>
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Nome da variavel
              </label>
              <input
                type="text"
                value={varName}
                onChange={(e) => {
                  setVarName(e.target.value)
                  if (varNameError) setVarNameError(null)
                }}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault()
                    handleSubmitForm()
                  }
                }}
                placeholder="ex: DB_CONN"
                autoFocus
                disabled={Boolean(pending)}
                className={cn(
                  "w-full rounded-lg border bg-background px-2.5 py-1.5 font-mono text-xs text-foreground outline-none transition",
                  varNameError
                    ? "border-destructive focus:ring-2 focus:ring-destructive/30"
                    : "border-input focus:border-ring focus:ring-2 focus:ring-ring/20",
                )}
              />
              {varNameError ? (
                <span className="text-[10px] text-destructive">{varNameError}</span>
              ) : null}
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                Tipo do banco
              </label>
              <div className="grid grid-cols-3 gap-1">
                {CONNECTION_TYPE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    type="button"
                    onClick={() => setVarType(opt.value)}
                    disabled={Boolean(pending)}
                    className={cn(
                      "rounded-lg border px-2 py-1 text-[11px] font-medium transition",
                      varType === opt.value
                        ? "border-primary bg-primary/10 text-foreground"
                        : "border-border bg-background/70 text-muted-foreground hover:border-primary/40 hover:text-foreground",
                      "disabled:cursor-not-allowed disabled:opacity-60",
                    )}
                  >
                    {opt.label}
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={handleSubmitForm}
                disabled={Boolean(pending)}
                className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-[11px] font-semibold text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {pending ? (
                  <MorphLoader className="size-3" />
                ) : (
                  <Check className="size-3" />
                )}
                Confirmar variavel
              </button>
              <button
                type="button"
                onClick={() => {
                  setFormOpen(false)
                  setVarNameError(null)
                }}
                disabled={Boolean(pending)}
                className="rounded-lg border border-border bg-background px-3 py-1.5 text-[11px] font-medium text-muted-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
              >
                Voltar
              </button>
            </div>
          </div>
        ) : null}

        {isAnswered && answer ? (
          <p className="text-[10px] text-muted-foreground">
            <span className="font-semibold">Sua escolha:</span> {answer}
          </p>
        ) : null}
      </div>
    </div>
  )
}
