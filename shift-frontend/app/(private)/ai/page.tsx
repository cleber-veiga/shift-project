"use client"

import { useSearchParams } from "next/navigation"
import { useEffect } from "react"
import { Sparkles } from "lucide-react"
import { useAIContext } from "@/lib/context/ai-context"
import { useAIPanelContext } from "@/lib/context/ai-panel-context"
import { useAIStream } from "@/lib/hooks/use-ai-stream"
import { AIMessageList } from "@/components/agent/ai-message-list"
import { AIInputBox } from "@/components/agent/ai-input-box"
import { AIEmptyState } from "@/components/agent/ai-empty-state"
import { AIErrorBanner } from "@/components/agent/ai-error-banner"

export default function AiFullScreenPage() {
  const params = useSearchParams()
  const threadId = params.get("threadId")
  const context = useAIContext()
  const { setActiveThread } = useAIPanelContext()
  const {
    messages,
    isStreaming,
    error,
    sendMessage,
    approve,
    reject,
    answerClarification,
    clearError,
  } = useAIStream()

  useEffect(() => {
    if (threadId) setActiveThread(threadId)
  }, [threadId, setActiveThread])

  const hasPendingApproval = messages.some((m) => m.approvalStatus === "pending")

  const handleSend = async (message: string) => {
    await sendMessage(message, context)
  }

  const handleClarify = async (selection: {
    option: { value: string; label: string; hint?: string }
    field: "connection_id" | "trigger_type" | "workflow_id" | "target_table" | "other"
    question: string
    isExtra: boolean
  }) => {
    await answerClarification(
      {
        kind: "option",
        field: selection.field,
        question: selection.question,
        option: selection.option,
        isExtra: selection.isExtra,
      },
      context,
    )
  }

  return (
    <div className="flex h-full flex-col">
      {/* Cabecalho */}
      <div className="flex h-12 shrink-0 items-center gap-2 border-b border-border px-6">
        <Sparkles className="size-4 text-primary" />
        <span className="text-sm font-semibold text-foreground">Shift AI</span>
        {threadId ? (
          <span className="text-xs text-muted-foreground">· Conversa carregada</span>
        ) : null}
      </div>

      {/* Area central com largura maxima */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="mx-auto flex w-full max-w-[800px] flex-1 flex-col overflow-hidden px-4">
          {error ? (
            <AIErrorBanner message={error} onDismiss={clearError} />
          ) : null}

          {messages.length === 0 ? (
            <AIEmptyState onSuggestionClick={(s) => void handleSend(s)} />
          ) : (
            <AIMessageList
              messages={messages}
              isStreaming={isStreaming}
              onApprove={approve}
              onReject={reject}
              onClarify={handleClarify}
            />
          )}

          <AIInputBox
            onSend={(msg) => void handleSend(msg)}
            disabled={isStreaming}
            awaitingApproval={hasPendingApproval}
          />
        </div>
      </div>
    </div>
  )
}
