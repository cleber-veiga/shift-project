"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { ChevronDown } from "lucide-react"
import type { AgentMessage } from "@/lib/types/ai-panel"
import { AIMessage } from "@/components/agent/ai-message"

const SCROLL_THRESHOLD = 40

interface AIMessageListProps {
  messages: AgentMessage[]
  onApprove: (approvalId: string) => Promise<void>
  onReject: (approvalId: string, reason?: string) => Promise<void>
}

export function AIMessageList({ messages, onApprove, onReject }: AIMessageListProps) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [showScrollBtn, setShowScrollBtn] = useState(false)
  const isAtBottomRef = useRef(true)

  const isNearBottom = useCallback(() => {
    const el = scrollRef.current
    if (!el) return true
    return el.scrollTop + el.clientHeight >= el.scrollHeight - SCROLL_THRESHOLD
  }, [])

  const scrollToBottom = useCallback(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" })
  }, [])

  // Scroll automatico quando nova mensagem chega, se ja estava no fim
  useEffect(() => {
    if (isAtBottomRef.current) {
      scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight })
    }
  }, [messages])

  const handleScroll = useCallback(() => {
    const near = isNearBottom()
    isAtBottomRef.current = near
    setShowScrollBtn(!near)
  }, [isNearBottom])

  return (
    <div className="relative min-h-0 flex-1 overflow-hidden">
      <div
        ref={scrollRef}
        role="log"
        aria-live="polite"
        aria-label="Mensagens da conversa"
        onScroll={handleScroll}
        className="h-full overflow-y-auto px-3 py-3 space-y-4"
      >
        {messages.map((msg) => (
          <AIMessage
            key={msg.id}
            message={msg}
            onApprove={onApprove}
            onReject={onReject}
          />
        ))}
        {/* Ancora para scroll */}
        <div aria-hidden />
      </div>

      {showScrollBtn ? (
        <button
          type="button"
          onClick={() => {
            scrollToBottom()
            setShowScrollBtn(false)
            isAtBottomRef.current = true
          }}
          className="absolute bottom-3 left-1/2 -translate-x-1/2 inline-flex items-center gap-1.5 rounded-full border border-border bg-card px-3 py-1.5 text-xs text-muted-foreground shadow-md hover:bg-accent transition-colors"
          aria-label="Ir para ultima mensagem"
        >
          <ChevronDown className="size-3.5" />
          Rolar para baixo
        </button>
      ) : null}
    </div>
  )
}
