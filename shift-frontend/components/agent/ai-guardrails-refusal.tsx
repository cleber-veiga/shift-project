"use client"

import { ShieldAlert } from "lucide-react"

interface AIGuardrailsRefusalProps {
  reason: string
}

export function AIGuardrailsRefusal({ reason }: AIGuardrailsRefusalProps) {
  return (
    <div className="flex items-start gap-2 rounded-xl border border-warning/30 bg-warning/10 px-3 py-2.5 text-xs text-warning-foreground">
      <ShieldAlert className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
      <div>
        <p className="mb-0.5 font-semibold text-amber-600 dark:text-amber-400">Solicitacao recusada</p>
        <p className="leading-relaxed text-muted-foreground">{reason}</p>
      </div>
    </div>
  )
}
