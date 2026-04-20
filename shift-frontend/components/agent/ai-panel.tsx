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
        onApprove={approve}
        onReject={reject}
      />
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
