"use client"

import { useState } from "react"
import { Check, ChevronDown, ClipboardList, ExternalLink, TriangleAlert, X } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ProposedPlan } from "@/lib/types/ai-panel"
import { AIApprovalActions } from "@/components/agent/ai-approval-actions"
import { useAINavigation } from "@/lib/hooks/use-ai-navigation"

interface AIPlanCardProps {
  plan: ProposedPlan
  approvalId?: string
  approvalStatus?: "pending" | "approved" | "rejected"
  approvalRejectedReason?: string
  onApprove?: (approvalId: string) => Promise<void>
  onReject?: (approvalId: string, reason?: string) => Promise<void>
}

export function AIPlanCard({
  plan,
  approvalId,
  approvalStatus,
  approvalRejectedReason,
  onApprove,
  onReject,
}: AIPlanCardProps) {
  const [expandedSteps, setExpandedSteps] = useState<Set<number>>(new Set([1]))
  const { navigateTo } = useAINavigation()

  const toggleStep = (step: number) => {
    setExpandedSteps((prev) => {
      const next = new Set(prev)
      if (next.has(step)) next.delete(step)
      else next.add(step)
      return next
    })
  }

  // Extrai IDs de workflow das tool calls para botao de navegacao
  const workflowId = plan.steps
    .flatMap((s) => s.toolCalls)
    .find((tc) => tc.arguments.workflow_id || tc.arguments.id)
    ?.arguments?.workflow_id as string | undefined
    ?? plan.steps
      .flatMap((s) => s.toolCalls)
      .find((tc) => typeof tc.arguments.id === "string")
      ?.arguments?.id as string | undefined

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card">
      {/* Cabecalho */}
      <div className="flex items-center gap-2 border-b border-border px-3 py-2.5">
        <ClipboardList className="size-3.5 shrink-0 text-primary" />
        <span className="text-xs font-semibold text-foreground">Plano proposto</span>
        {approvalStatus === "approved" ? (
          <span className="ml-auto flex items-center gap-1 rounded-full bg-emerald-500/15 px-2 py-0.5 text-[10px] font-semibold text-emerald-600 dark:text-emerald-400">
            <Check className="size-3" /> Aprovado
          </span>
        ) : approvalStatus === "rejected" ? (
          <span className="ml-auto flex items-center gap-1 rounded-full bg-destructive/15 px-2 py-0.5 text-[10px] font-semibold text-destructive">
            <X className="size-3" /> Rejeitado
          </span>
        ) : approvalStatus === "pending" ? (
          <span className="ml-auto rounded-full bg-amber-500/15 px-2 py-0.5 text-[10px] font-semibold text-amber-600 dark:text-amber-400">
            Aguardando
          </span>
        ) : null}
      </div>

      <div className="p-3 space-y-3">
        {/* Intencao */}
        <div>
          <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
            Intencao
          </p>
          <p className="mt-0.5 text-xs text-foreground">{plan.intent}</p>
        </div>

        {/* Steps */}
        <div className="flex flex-col gap-1.5">
          {plan.steps.map((step) => {
            const isExpanded = expandedSteps.has(step.step)
            const hasDestructive = step.toolCalls.some((tc) => tc.requiresApproval)

            return (
              <div key={step.step} className="rounded-lg border border-border bg-background/50">
                <button
                  type="button"
                  onClick={() => toggleStep(step.step)}
                  className="flex w-full items-center gap-2 px-2.5 py-2 text-left"
                >
                  <span className="size-4 shrink-0 rounded-full bg-primary/15 text-center text-[10px] font-bold leading-4 text-primary">
                    {step.step}
                  </span>
                  <span className="flex-1 text-xs text-foreground">{step.description}</span>
                  {hasDestructive ? (
                    <TriangleAlert className="size-3 shrink-0 text-amber-500" />
                  ) : null}
                  <ChevronDown
                    className={cn("size-3.5 shrink-0 text-muted-foreground transition-transform", isExpanded && "rotate-180")}
                  />
                </button>

                {isExpanded ? (
                  <div className="border-t border-border px-2.5 pb-2 pt-1.5 space-y-1.5">
                    {step.toolCalls.map((tc, idx) => (
                      <div key={idx} className="text-xs">
                        <div className="flex items-center gap-1.5">
                          <span className="font-mono text-primary">{tc.toolName}</span>
                          {tc.requiresApproval ? (
                            <span className="flex items-center gap-0.5 rounded bg-amber-500/15 px-1 text-[10px] font-semibold text-amber-600 dark:text-amber-400">
                              <TriangleAlert className="size-2.5" /> destrutivo
                            </span>
                          ) : null}
                        </div>
                        {Object.keys(tc.arguments).length > 0 ? (
                          <p className="mt-0.5 font-mono text-[10px] text-muted-foreground">
                            {Object.entries(tc.arguments)
                              .slice(0, 3)
                              .map(([k, v]) => `${k}: ${JSON.stringify(v)}`)
                              .join(", ")}
                          </p>
                        ) : null}
                        {tc.rationale ? (
                          <p className="mt-0.5 text-[10px] text-muted-foreground/70 italic">
                            {tc.rationale}
                          </p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
              </div>
            )
          })}
        </div>

        {/* Impacto */}
        {plan.impact ? (
          <p className="text-[11px] text-muted-foreground">
            <span className="font-semibold text-foreground">Impacto estimado:</span> {plan.impact}
          </p>
        ) : null}

        {/* Rejeicao reason */}
        {approvalStatus === "rejected" && approvalRejectedReason ? (
          <p className="text-[11px] text-muted-foreground">
            <span className="font-semibold">Motivo:</span> {approvalRejectedReason}
          </p>
        ) : null}

        {/* Botao navegar + acoes */}
        <div className="flex flex-col gap-2">
          {workflowId ? (
            <button
              type="button"
              onClick={() => navigateTo(`/workflow/${workflowId}`)}
              className="inline-flex items-center gap-1.5 self-start rounded-lg border border-border bg-card px-2.5 py-1.5 text-[11px] font-medium text-foreground transition hover:bg-accent"
            >
              <ExternalLink className="size-3" />
              Ver workflow
            </button>
          ) : null}

          {approvalStatus === "pending" && approvalId && onApprove && onReject ? (
            <AIApprovalActions
              approvalId={approvalId}
              onApprove={onApprove}
              onReject={onReject}
            />
          ) : null}
        </div>
      </div>
    </div>
  )
}
