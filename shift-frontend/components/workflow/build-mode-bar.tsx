"use client"

import { Bot, Check, X } from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { cn } from "@/lib/utils"
import type { BuildModeState } from "@/lib/workflow/build-mode-context"

interface BuildModeBarProps {
  buildState: BuildModeState
  pendingNodeCount: number
  pendingEdgeCount: number
  isConfirming: boolean
  isCancelling: boolean
  error: string | null
  onConfirm: () => void
  onCancel: () => void
}

export function BuildModeBar({
  buildState,
  pendingNodeCount,
  pendingEdgeCount,
  isConfirming,
  isCancelling,
  error,
  onConfirm,
  onCancel,
}: BuildModeBarProps) {
  const isAwaiting = buildState === "awaiting_confirmation"
  const busy = isConfirming || isCancelling

  return (
    <div
      className={cn(
        "flex h-10 shrink-0 items-center justify-between gap-3 px-4 text-sm transition-colors",
        isAwaiting
          ? "bg-violet-500/10 border-b border-violet-400/30"
          : "bg-amber-500/10 border-b border-amber-400/30",
      )}
    >
      {/* Left: status label */}
      <div className="flex items-center gap-2 min-w-0">
        <Bot
          className={cn(
            "size-4 shrink-0",
            isAwaiting ? "text-violet-500" : "text-amber-500 animate-pulse",
          )}
        />
        <span
          className={cn(
            "font-medium truncate",
            isAwaiting ? "text-violet-700 dark:text-violet-300" : "text-amber-700 dark:text-amber-300",
          )}
        >
          {isAwaiting ? "IA aguarda confirmação" : "IA está construindo…"}
        </span>

        {/* Counters */}
        {(pendingNodeCount > 0 || pendingEdgeCount > 0) && (
          <div className="flex items-center gap-1.5 ml-1">
            {pendingNodeCount > 0 && (
              <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-[11px] font-semibold text-violet-600 dark:text-violet-300">
                {pendingNodeCount} {pendingNodeCount === 1 ? "nó" : "nós"}
              </span>
            )}
            {pendingEdgeCount > 0 && (
              <span className="rounded-full bg-violet-500/15 px-2 py-0.5 text-[11px] font-semibold text-violet-600 dark:text-violet-300">
                {pendingEdgeCount} {pendingEdgeCount === 1 ? "aresta" : "arestas"}
              </span>
            )}
          </div>
        )}

        {error && (
          <span className="ml-2 text-[11px] text-red-500 truncate">{error}</span>
        )}
      </div>

      {/* Right: action buttons (only when awaiting) */}
      {isAwaiting && (
        <div className="flex shrink-0 items-center gap-2">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="flex h-7 items-center gap-1.5 rounded-md border border-border bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
          >
            {isCancelling ? (
              <MorphLoader className="size-3" />
            ) : (
              <X className="size-3" />
            )}
            Cancelar
          </button>

          <button
            type="button"
            onClick={onConfirm}
            disabled={busy || pendingNodeCount === 0}
            className="flex h-7 items-center gap-1.5 rounded-md bg-violet-600 px-2.5 text-xs font-semibold text-white transition-colors hover:bg-violet-700 disabled:opacity-50"
          >
            {isConfirming ? (
              <MorphLoader className="size-3" />
            ) : (
              <Check className="size-3" />
            )}
            Confirmar
          </button>
        </div>
      )}

      {/* Cancel-only button during building phase */}
      {!isAwaiting && (
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-border bg-background px-2.5 text-xs font-medium text-foreground transition-colors hover:bg-muted disabled:opacity-50"
        >
          {isCancelling ? (
            <MorphLoader className="size-3" />
          ) : (
            <X className="size-3" />
          )}
          Interromper
        </button>
      )}
    </div>
  )
}
