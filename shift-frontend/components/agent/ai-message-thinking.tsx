"use client"

import { MorphLoader } from "@/components/ui/morph-loader"

const NODE_LABELS: Record<string, string> = {
  starting: "Iniciando agente...",
  guardrails: "Verificando guardrails...",
  understand_intent: "Entendendo a intencao...",
  plan_actions: "Planejando acoes...",
  execute: "Executando...",
  report: "Preparando resposta...",
  build_workflow: "Construindo workflow...",
  human_approval: "Aguardando aprovacao...",
}

interface AIMessageThinkingProps {
  node: string
}

export function AIMessageThinking({ node }: AIMessageThinkingProps) {
  const label = NODE_LABELS[node] ?? "Processando..."

  return (
    <div className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
      <MorphLoader className="size-3" />
      <span>{label}</span>
    </div>
  )
}
