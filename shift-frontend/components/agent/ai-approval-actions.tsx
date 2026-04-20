"use client"

import { useState } from "react"
import { Check, ChevronDown, X } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"

interface AIApprovalActionsProps {
  approvalId: string
  onApprove: (approvalId: string) => Promise<void>
  onReject: (approvalId: string, reason?: string) => Promise<void>
}

export function AIApprovalActions({ approvalId, onApprove, onReject }: AIApprovalActionsProps) {
  const [loading, setLoading] = useState<"approve" | "reject" | null>(null)
  const [showReason, setShowReason] = useState(false)
  const [reason, setReason] = useState("")

  const handleApprove = async () => {
    if (loading) return
    setLoading("approve")
    try {
      await onApprove(approvalId)
    } finally {
      setLoading(null)
    }
  }

  const handleReject = async () => {
    if (loading) return
    setLoading("reject")
    try {
      await onReject(approvalId, reason.trim() || undefined)
    } finally {
      setLoading(null)
      setShowReason(false)
    }
  }

  return (
    <div className="mt-3 flex flex-col gap-2">
      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleApprove}
          disabled={loading !== null}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
          aria-label="Aprovar plano"
        >
          {loading === "approve" ? (
            <MorphLoader className="size-3" />
          ) : (
            <Check className="size-3.5" />
          )}
          Aprovar
        </button>

        <button
          type="button"
          onClick={() => setShowReason((v) => !v)}
          disabled={loading !== null}
          className="inline-flex flex-1 items-center justify-center gap-1.5 rounded-xl border border-border bg-card px-3 py-2 text-xs font-semibold text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
          aria-label="Rejeitar plano"
        >
          <X className="size-3.5" />
          Rejeitar
          <ChevronDown className={`size-3 transition-transform ${showReason ? "rotate-180" : ""}`} />
        </button>
      </div>

      {showReason ? (
        <div className="flex flex-col gap-2">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Motivo (opcional)..."
            rows={2}
            className="w-full resize-none rounded-xl border border-input bg-background/70 px-3 py-2 text-xs text-foreground placeholder:text-muted-foreground outline-none focus:border-ring focus:ring-2 focus:ring-ring/20"
          />
          <button
            type="button"
            onClick={handleReject}
            disabled={loading !== null}
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-destructive/40 bg-destructive/10 px-3 py-2 text-xs font-semibold text-destructive transition hover:bg-destructive/20 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {loading === "reject" ? <MorphLoader className="size-3" /> : <X className="size-3.5" />}
            Confirmar rejeicao
          </button>
        </div>
      ) : null}
    </div>
  )
}
