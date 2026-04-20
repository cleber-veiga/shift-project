"use client"

import { useState } from "react"
import { RotateCcw } from "lucide-react"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import { cn } from "@/lib/utils"
import type { AgentMessage } from "@/lib/types/ai-panel"
import { AIMessageThinking } from "@/components/agent/ai-message-thinking"
import { AIGuardrailsRefusal } from "@/components/agent/ai-guardrails-refusal"
import { AIExecutionProgress } from "@/components/agent/ai-execution-progress"
import { AIPlanCard } from "@/components/agent/ai-plan-card"

function formatRelativeTime(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime()
  const minutes = Math.floor(diff / 60000)
  if (minutes < 1) return "agora"
  if (minutes < 60) return `ha ${minutes}min`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `ha ${hours}h`
  return `ha ${Math.floor(hours / 24)}d`
}

interface AIMessageProps {
  message: AgentMessage
  onApprove?: (approvalId: string) => Promise<void>
  onReject?: (approvalId: string, reason?: string) => Promise<void>
  onRetry?: () => void
}

export function AIMessage({ message, onApprove, onReject, onRetry }: AIMessageProps) {
  const [showTime, setShowTime] = useState(false)
  const isUser = message.role === "user"

  if (isUser) {
    return (
      <div
        className="flex justify-end"
        onMouseEnter={() => setShowTime(true)}
        onMouseLeave={() => setShowTime(false)}
      >
        <div className="max-w-[85%]">
          {message.failed ? (
            <div className="mb-1 flex items-center justify-end gap-1.5 text-[10px] text-destructive">
              Falha ao enviar
              {onRetry ? (
                <button type="button" onClick={onRetry} className="hover:underline flex items-center gap-0.5">
                  <RotateCcw className="size-2.5" /> Tentar novamente
                </button>
              ) : null}
            </div>
          ) : null}
          <div className={cn(
            "rounded-xl rounded-tr-sm bg-primary/10 px-3 py-2 text-sm text-foreground",
            message.failed && "opacity-60",
          )}>
            <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
          </div>
          {showTime ? (
            <p className="mt-1 text-right text-[10px] text-muted-foreground/50">
              {formatRelativeTime(message.createdAt)}
            </p>
          ) : null}
        </div>
      </div>
    )
  }

  // Mensagem de assistente
  return (
    <div
      className="flex flex-col gap-2"
      onMouseEnter={() => setShowTime(true)}
      onMouseLeave={() => setShowTime(false)}
    >
      {/* Indicador de raciocinio */}
      {message.thinkingNode ? (
        <AIMessageThinking node={message.thinkingNode} />
      ) : null}

      {/* Plano proposto */}
      {message.planProposed ? (
        <AIPlanCard
          plan={message.planProposed}
          approvalId={message.approvalId}
          approvalStatus={message.approvalStatus}
          approvalRejectedReason={message.approvalRejectedReason}
          onApprove={onApprove}
          onReject={onReject}
        />
      ) : null}

      {/* Recusa de guardrails */}
      {message.isGuardrailsRefusal && message.content ? (
        <AIGuardrailsRefusal reason={message.content} />
      ) : null}

      {/* Progresso de execucao */}
      {message.toolCallsExecuted && message.toolCallsExecuted.length > 0 ? (
        <AIExecutionProgress toolCalls={message.toolCallsExecuted} />
      ) : null}

      {/* Texto da resposta */}
      {message.content && !message.isGuardrailsRefusal ? (
        <div className="text-sm text-foreground leading-relaxed">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              p: ({ children }) => <p className="mb-2 last:mb-0">{children}</p>,
              code: ({ children, className }) => {
                const isBlock = className?.includes("language-")
                return isBlock ? (
                  <code className="block overflow-x-auto rounded-lg bg-muted p-3 font-mono text-xs leading-relaxed">{children}</code>
                ) : (
                  <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">{children}</code>
                )
              },
              pre: ({ children }) => <pre className="mb-2">{children}</pre>,
              ul: ({ children }) => <ul className="mb-2 ml-4 list-disc space-y-0.5">{children}</ul>,
              ol: ({ children }) => <ol className="mb-2 ml-4 list-decimal space-y-0.5">{children}</ol>,
              strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
            }}
          >
            {message.content}
          </ReactMarkdown>
          {message.isStreaming ? (
            <span className="inline-block h-3.5 w-0.5 animate-pulse bg-foreground/60 align-middle" />
          ) : null}
        </div>
      ) : null}

      {showTime && !message.isStreaming ? (
        <p className="text-[10px] text-muted-foreground/50">
          {formatRelativeTime(message.createdAt)}
        </p>
      ) : null}
    </div>
  )
}
