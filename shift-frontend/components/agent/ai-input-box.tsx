"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { ArrowUp } from "lucide-react"
import { cn } from "@/lib/utils"
import { useAIContext } from "@/lib/context/ai-context"
import type { AIContextValue } from "@/lib/types/ai-context"

const MAX_CHARS = 8000
const WARN_CHARS = 6000

function contextSummary(context: AIContextValue): string | null {
  switch (context.section) {
    case "workflows_list":
      return `${context.workflows.length} workflows`
    case "workflow_editor":
      return `Workflow: ${context.workflow.name}`
    case "connections":
      return `${context.connections.length} conexoes`
    case "playground":
      return `Conexao: ${context.connection.name}`
    case "project_members":
      return `${context.members.length} membros`
    case "home":
      return "Visao geral"
    default:
      return null
  }
}

function placeholderForContext(context: AIContextValue): string {
  switch (context.section) {
    case "workflows_list":
      return "Pergunte sobre seus workflows..."
    case "workflow_editor":
      return `Pergunte sobre o workflow ${context.workflow.name}...`
    case "connections":
      return "Pergunte sobre suas conexoes..."
    case "playground":
      return `Pergunte sobre ${context.connection.name}...`
    default:
      return "Como posso ajudar?"
  }
}

interface AIInputBoxProps {
  onSend: (message: string) => void
  disabled: boolean
  awaitingApproval: boolean
}

export function AIInputBox({ onSend, disabled, awaitingApproval }: AIInputBoxProps) {
  const context = useAIContext()
  const [text, setText] = useState("")
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const summary = contextSummary(context)
  const isDisabled = disabled || awaitingApproval

  // Ajuste automatico de altura
  useEffect(() => {
    const el = textareaRef.current
    if (!el) return
    el.style.height = "auto"
    const lineHeight = 20
    const maxHeight = lineHeight * 5 + 16
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`
  }, [text])

  const handleSend = useCallback(() => {
    const trimmed = text.trim()
    if (!trimmed || isDisabled) return
    onSend(trimmed)
    setText("")
  }, [text, isDisabled, onSend])

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="mt-auto shrink-0 border-t border-border bg-background px-3 pb-3 pt-2">
      {awaitingApproval ? (
        <p className="mb-2 text-center text-[11px] text-amber-600 dark:text-amber-400">
          Aprovacao pendente — responda acima para continuar
        </p>
      ) : null}

      <div className={cn(
        "flex flex-col gap-2 rounded-xl border bg-card px-3 py-2.5 transition-colors",
        isDisabled ? "border-border opacity-60" : "border-input focus-within:border-ring focus-within:ring-2 focus-within:ring-ring/20",
      )}>
        <textarea
          ref={textareaRef}
          value={text}
          onChange={(e) => setText(e.target.value.slice(0, MAX_CHARS))}
          onKeyDown={handleKeyDown}
          placeholder={awaitingApproval ? "Aprovacao necessaria antes de continuar" : placeholderForContext(context)}
          disabled={isDisabled}
          rows={1}
          className="resize-none bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none disabled:cursor-not-allowed"
          aria-label="Mensagem para o assistente"
        />

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-[10px] text-muted-foreground/60">
            {summary ? <span>Contexto: {summary}</span> : null}
            {text.length > WARN_CHARS ? (
              <span className="text-amber-500">{text.length}/{MAX_CHARS}</span>
            ) : null}
          </div>

          <button
            type="button"
            onClick={handleSend}
            disabled={isDisabled || !text.trim()}
            className="inline-flex size-7 items-center justify-center rounded-lg bg-primary text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-40"
            aria-label="Enviar mensagem"
          >
            <ArrowUp className="size-3.5" />
          </button>
        </div>
      </div>

      <p className="mt-1.5 text-center text-[10px] text-muted-foreground/40">
        Enter para enviar · Shift+Enter para nova linha
      </p>
    </div>
  )
}
