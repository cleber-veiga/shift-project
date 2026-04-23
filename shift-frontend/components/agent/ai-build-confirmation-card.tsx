"use client"

import { Check, Hammer, Loader2, X } from "lucide-react"
import { useAIContext } from "@/lib/context/ai-context"
import { useBuildMode } from "@/lib/workflow/build-mode-context"

/**
 * Card renderizado no chat quando o agente terminou de propor os ghost
 * nodes/edges e esta aguardando o usuario confirmar a aplicacao no canvas.
 *
 * Substitui (ou complementa) a BuildModeBar do canvas — o usuario pode
 * aprovar/cancelar sem sair do fluxo de conversa com a IA.
 *
 * So aparece quando:
 *  - buildState === "awaiting_confirmation"
 *  - estamos no editor de workflow (contexto precisa do workflow.id)
 */
export function AIBuildConfirmationCard() {
  const context = useAIContext()
  const {
    buildState,
    pendingNodes,
    pendingEdges,
    isConfirming,
    isCancelling,
    error,
    confirmBuild,
    cancelBuild,
  } = useBuildMode()

  // So renderiza se o build esta aguardando confirmacao E estamos no editor
  // de workflow (precisamos do workflow.id para disparar confirmBuild).
  if (buildState !== "awaiting_confirmation") return null
  if (context.section !== "workflow_editor") return null

  const workflowId = context.workflow.id
  const nodeCount = pendingNodes.length
  const edgeCount = pendingEdges.length
  const busy = isConfirming || isCancelling

  return (
    <div className="overflow-hidden rounded-xl border border-violet-400/40 bg-violet-500/5">
      <div className="flex items-center gap-2 border-b border-violet-400/30 bg-violet-500/10 px-3 py-2.5">
        <Hammer className="size-3.5 shrink-0 text-violet-600 dark:text-violet-400" />
        <span className="text-xs font-semibold text-foreground">
          Confirmar construcao
        </span>
        <span className="ml-auto rounded-full bg-violet-500/15 px-2 py-0.5 text-[10px] font-semibold text-violet-600 dark:text-violet-400">
          Aguardando
        </span>
      </div>

      <div className="space-y-2.5 p-3">
        <p className="text-xs text-muted-foreground">
          O agente propos{" "}
          <span className="font-semibold text-foreground">
            {nodeCount} no{nodeCount !== 1 ? "s" : ""}
          </span>
          {edgeCount > 0 ? (
            <>
              {" "}e{" "}
              <span className="font-semibold text-foreground">
                {edgeCount} conexao{edgeCount !== 1 ? "es" : ""}
              </span>
            </>
          ) : null}
          . Revise os nos fantasmas no canvas e confirme para aplica-los.
        </p>

        {error ? (
          <p className="rounded-md border border-destructive/40 bg-destructive/10 px-2 py-1.5 text-[11px] text-destructive">
            {error}
          </p>
        ) : null}

        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => void confirmBuild(workflowId)}
            disabled={busy || nodeCount === 0}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-violet-600 px-3 py-2 text-xs font-semibold text-white transition hover:bg-violet-700 disabled:cursor-not-allowed disabled:opacity-60"
            aria-label="Confirmar construcao"
          >
            {isConfirming ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Check className="size-3.5" />
            )}
            Confirmar
          </button>

          <button
            type="button"
            onClick={() => void cancelBuild(workflowId)}
            disabled={busy}
            className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-border bg-card px-3 py-2 text-xs font-semibold text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
            aria-label="Cancelar construcao"
          >
            {isCancelling ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <X className="size-3.5" />
            )}
            Cancelar
          </button>
        </div>
      </div>
    </div>
  )
}
