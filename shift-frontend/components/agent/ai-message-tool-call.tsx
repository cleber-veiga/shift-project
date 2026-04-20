"use client"

import { Check, Loader2, X } from "lucide-react"
import { cn } from "@/lib/utils"
import type { ExecutedToolCall } from "@/lib/types/ai-panel"

interface AIMessageToolCallProps {
  toolCall: ExecutedToolCall
}

export function AIMessageToolCall({ toolCall }: AIMessageToolCallProps) {
  return (
    <div className="flex items-center gap-2 py-0.5 text-xs text-muted-foreground">
      {toolCall.running ? (
        <Loader2 className="size-3 animate-spin text-primary" />
      ) : toolCall.success ? (
        <Check className="size-3 text-emerald-500" />
      ) : (
        <X className="size-3 text-destructive" />
      )}

      <span className={cn("font-mono", toolCall.running && "text-foreground")}>
        {toolCall.toolName}
      </span>

      {toolCall.running ? (
        <span className="text-muted-foreground/60">executando...</span>
      ) : toolCall.success ? (
        <span className="text-muted-foreground/60">{toolCall.durationMs}ms</span>
      ) : (
        <span className="text-destructive/80">{toolCall.error ?? "falhou"}</span>
      )}
    </div>
  )
}
