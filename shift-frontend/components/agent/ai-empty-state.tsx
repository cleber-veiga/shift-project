"use client"

import { BotMessageSquare } from "lucide-react"
import { useAIContext } from "@/lib/context/ai-context"
import { useDashboard } from "@/lib/context/dashboard-context"
import { getStoredSession } from "@/lib/auth"
import type { AIContextValue } from "@/lib/types/ai-context"

function getSuggestions(context: AIContextValue): string[] {
  switch (context.section) {
    case "workflows_list":
      return [
        "Liste os workflows que falharam recentemente",
        "Quais workflows estao publicados?",
        "Execute o workflow mais recente",
        "Crie um resumo dos workflows deste projeto",
      ]
    case "workflow_editor":
      return [
        "Explique o que este workflow faz",
        "Execute este workflow agora",
        "Quais nos podem causar erros?",
        "Sugira melhorias para este fluxo",
      ]
    case "connections":
      return [
        "Liste as conexoes disponiveis",
        "Qual conexao esta com problema?",
        "Teste todas as conexoes do workspace",
      ]
    case "playground":
      return [
        `Liste as tabelas da conexao ${context.connection.name}`,
        "Quantos registros ha na tabela principal?",
        "Escreva uma query de exemplo",
      ]
    case "home":
      return [
        "Quais workflows executaram hoje?",
        "Ha alguma execucao com falha?",
        "Liste meus projetos ativos",
        "O que mais precisa de atencao agora?",
      ]
    default:
      return [
        "O que voce pode fazer por mim?",
        "Liste os workflows do workspace",
        "Mostre as ultimas execucoes",
      ]
  }
}

interface AIEmptyStateProps {
  onSuggestionClick: (text: string) => void
}

export function AIEmptyState({ onSuggestionClick }: AIEmptyStateProps) {
  const context = useAIContext()
  const { selectedProject, selectedWorkspace } = useDashboard()
  const session = typeof window !== "undefined" ? getStoredSession() : null
  const userName = session?.user?.full_name?.split(" ")[0] ?? "voce"
  const scopeName = selectedProject?.name ?? selectedWorkspace?.name ?? "seu workspace"
  const suggestions = getSuggestions(context)

  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-4 px-5 py-8 text-center">
      <div className="flex size-14 items-center justify-center rounded-2xl bg-primary/10 text-primary">
        <BotMessageSquare className="size-7" />
      </div>

      <div>
        <p className="text-sm font-semibold text-foreground">
          Ola, {userName}.
        </p>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Como posso ajudar em {scopeName}?
        </p>
      </div>

      <div className="flex w-full flex-col gap-1.5">
        {suggestions.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => onSuggestionClick(s)}
            className="rounded-xl border border-border bg-card px-3 py-2.5 text-left text-xs text-foreground transition hover:bg-accent hover:border-ring/40"
          >
            {s}
          </button>
        ))}
      </div>
    </div>
  )
}
