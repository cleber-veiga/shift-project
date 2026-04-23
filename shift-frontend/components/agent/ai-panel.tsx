"use client"

import { useEffect, useRef } from "react"
import { useAIPanelContext } from "@/lib/context/ai-panel-context"
import { useAIContext } from "@/lib/context/ai-context"
import { useAIStream } from "@/lib/hooks/use-ai-stream"
import { AIPanelHeader } from "@/components/agent/ai-panel-header"
import { AIPanelResizeHandle } from "@/components/agent/ai-panel-resize-handle"
import { AIEmptyState } from "@/components/agent/ai-empty-state"
import { AIMessageList } from "@/components/agent/ai-message-list"
import { AIInputBox } from "@/components/agent/ai-input-box"
import { AIErrorBanner } from "@/components/agent/ai-error-banner"
import { AIRateLimitBanner } from "@/components/agent/ai-rate-limit-banner"
import { AIThreadHistory } from "@/components/agent/ai-thread-history"
import { AIBuildConfirmationCard } from "@/components/agent/ai-build-confirmation-card"
import type { ClarificationSelection } from "@/components/agent/ai-clarification-card"

function AIConversation() {
  const context = useAIContext()
  const {
    messages,
    isStreaming,
    error,
    rateLimit,
    sendMessage,
    approve,
    reject,
    answerClarification,
    clearError,
    clearRateLimit,
  } = useAIStream()
  const { activeThreadId } = useAIPanelContext()

  const hasPendingApproval = messages.some(
    (m) => m.approvalStatus === "pending",
  )

  const handleSend = async (message: string) => {
    await sendMessage(message, context)
  }

  // Chip de clarificacao clicado: delega ao hook, que ja marca a mensagem
  // anterior como respondida e envia a escolha como nova mensagem. A
  // selecao chega estruturada (field + opcao) para o hook poder ancorar o
  // contexto na mensagem enviada ao planner.
  const handleClarify = async (selection: ClarificationSelection) => {
    await answerClarification(
      {
        kind: "option",
        field: selection.field,
        question: selection.question,
        option: selection.option,
        isExtra: selection.isExtra,
        connectionVariable: selection.connectionVariable,
      },
      context,
    )
  }

  if (!activeThreadId && messages.length === 0) {
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        {rateLimit ? (
          <AIRateLimitBanner
            message={rateLimit.message}
            retryAfterSeconds={rateLimit.retryAfterSeconds}
            onDismiss={clearRateLimit}
          />
        ) : null}
        <AIEmptyState onSuggestionClick={(s) => void handleSend(s)} />
        <AIInputBox
          onSend={(msg) => void handleSend(msg)}
          disabled={isStreaming || rateLimit !== null}
          awaitingApproval={false}
        />
      </div>
    )
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      {rateLimit ? (
        <AIRateLimitBanner
          message={rateLimit.message}
          retryAfterSeconds={rateLimit.retryAfterSeconds}
          onDismiss={clearRateLimit}
        />
      ) : null}
      {error && !rateLimit ? (
        <AIErrorBanner message={error} onDismiss={clearError} />
      ) : null}
      <AIMessageList
        messages={messages}
        isStreaming={isStreaming}
        onApprove={approve}
        onReject={reject}
        onClarify={handleClarify}
      />
      {/* Confirmacao de build aparece logo acima do input quando o agente
          termina de propor os ghost nodes — mantem tudo no chat, sem exigir
          que o usuario saia para a barra flutuante do canvas. */}
      <div className="px-3 pb-2 empty:hidden">
        <AIBuildConfirmationCard />
      </div>
      <AIInputBox
        onSend={(msg) => void handleSend(msg)}
        disabled={isStreaming || rateLimit !== null}
        awaitingApproval={hasPendingApproval}
      />
    </div>
  )
}

export function AIPanel() {
  const { isOpen, width, historyOpen, close } = useAIPanelContext()
  const panelRef = useRef<HTMLElement>(null)

  useEffect(() => {
    if (!isOpen) return
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") close()
    }
    document.addEventListener("keydown", onKeyDown)
    return () => document.removeEventListener("keydown", onKeyDown)
  }, [isOpen, close])

  if (!isOpen) return null

  return (
    <aside
      ref={panelRef}
      aria-label="Assistente Shift"
      className="sticky top-0 relative flex h-screen shrink-0 self-stretch flex-col border-l border-border bg-background transition-all duration-200"
      style={{ width: `${width}px` }}
    >
      <AIPanelResizeHandle />
      <AIPanelHeader />

      <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden">
        {historyOpen ? (
          <AIThreadHistory />
        ) : null}

        <AIConversation />
      </div>
    </aside>
  )
}
