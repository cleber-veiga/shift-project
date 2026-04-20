"use client"

import type { ExecutedToolCall } from "@/lib/types/ai-panel"
import { AIMessageToolCall } from "@/components/agent/ai-message-tool-call"

interface AIExecutionProgressProps {
  toolCalls: ExecutedToolCall[]
}

export function AIExecutionProgress({ toolCalls }: AIExecutionProgressProps) {
  if (toolCalls.length === 0) return null

  return (
    <div className="rounded-xl border border-border bg-muted/40 px-3 py-2">
      <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
        Execucao
      </p>
      <div className="flex flex-col gap-0.5">
        {toolCalls
          .slice()
          .sort((a, b) => a.step - b.step)
          .map((tc) => (
            <AIMessageToolCall key={tc.step} toolCall={tc} />
          ))}
      </div>
    </div>
  )
}
