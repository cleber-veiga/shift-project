"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import {
  Bot,
  Brain,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  PanelRightClose,
  Play,
  SendHorizontal,
  Sparkles,
  Square,
} from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import ReactMarkdown from "react-markdown"
import remarkGfm from "remark-gfm"
import {
  streamAiChat,
  getAiChatCapabilities,
  recordAiChatMemory,
  type AiChatMessage,
  type AiChatCapabilities,
} from "@/lib/auth"
import { Tooltip } from "@/components/ui/tooltip"

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ChatMessage {
  id: string
  role: "user" | "assistant"
  content: string
  timestamp: Date
  toolCalls?: { name: string; status: "calling" | "done" }[]
  reasoning?: string
  reasoningModel?: string
  deepReasoning?: boolean
}

// ─── Tool call labels ─────────────────────────────────────────────────────────

const TOOL_LABELS: Record<string, string> = {
  list_tables: "Listando tabelas",
  describe_table: "Descrevendo tabela",
  find_columns: "Buscando colunas",
  execute_select: "Executando consulta",
  get_sample_rows: "Amostrando dados",
  explain_query: "Analisando plano",
  get_relationships: "Mapeando relacionamentos",
}

// ─── Markdown code block with "Apply" button ─────────────────────────────────

function CodeBlock({
  children,
  className,
  onApply,
}: {
  children: React.ReactNode
  className?: string
  onApply?: (sql: string) => void
}) {
  const isSql = className?.includes("language-sql")
  const code = String(children).replace(/\n$/, "")
  const [copied, setCopied] = useState(false)

  function handleCopy() {
    void navigator.clipboard.writeText(code)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="group relative my-2 rounded-lg border border-border bg-muted/50">
      <pre className="overflow-x-auto p-3 font-mono text-[12px] leading-relaxed text-foreground">
        <code>{code}</code>
      </pre>
      <div className="flex items-center gap-1 border-t border-border px-2 py-1">
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          {copied ? <Check className="size-3" /> : <Copy className="size-3" />}
          {copied ? "Copiado" : "Copiar"}
        </button>
        {isSql && onApply && (
          <button
            type="button"
            onClick={() => onApply(code)}
            className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary transition-colors hover:bg-primary/20"
          >
            <Play className="size-3" />
            Aplicar no editor
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Tool call badge ──────────────────────────────────────────────────────────

function ToolBadge({ name, status }: { name: string; status: "calling" | "done" }) {
  const label = TOOL_LABELS[name] || name
  return (
    <div className="my-1 inline-flex items-center gap-1.5 rounded-md bg-muted/60 px-2 py-1 text-[10px] text-muted-foreground">
      {status === "calling" ? (
        <MorphLoader className="size-3" />
      ) : (
        <Check className="size-3 text-green-600 dark:text-green-400" />
      )}
      <span>{label}{status === "calling" ? "..." : ""}</span>
    </div>
  )
}

// ─── Reasoning block ──────────────────────────────────────────────────────────

function ReasoningBlock({
  text,
  streaming,
  model,
}: {
  text: string
  streaming: boolean
  model?: string
}) {
  const [open, setOpen] = useState(false)
  const hasText = text.trim().length > 0

  return (
    <div className="mb-2 rounded-md border border-border/60 bg-muted/30">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-2 py-1.5 text-left text-[11px] text-muted-foreground transition-colors hover:bg-muted"
      >
        {streaming ? (
          <MorphLoader className="size-3 shrink-0 text-primary" />
        ) : (
          <Brain className="size-3 shrink-0 text-primary" />
        )}
        <span className="font-medium">
          {streaming ? "Pensando" : "Raciocinio"}
          {model ? ` · ${model}` : ""}
        </span>
        {hasText && (
          <span className="ml-auto flex items-center gap-1 text-[10px]">
            {open ? "ocultar" : "ver"}
            {open ? (
              <ChevronDown className="size-3" />
            ) : (
              <ChevronRight className="size-3" />
            )}
          </span>
        )}
      </button>
      {open && hasText && (
        <div className="border-t border-border/60 px-3 py-2 text-[11px] italic leading-relaxed text-muted-foreground whitespace-pre-wrap">
          {text}
        </div>
      )}
    </div>
  )
}

// ─── Chat Panel ───────────────────────────────────────────────────────────────

export function ChatPanel({
  connectionId,
  onClose,
  onApplyQuery,
}: {
  connectionId: string
  onClose: () => void
  onApplyQuery?: (sql: string) => void
}) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState("")
  const [streaming, setStreaming] = useState(false)
  const [error, setError] = useState("")
  const [deepReasoning, setDeepReasoning] = useState(false)
  const [capabilities, setCapabilities] = useState<AiChatCapabilities | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    let active = true
    getAiChatCapabilities()
      .then((caps) => {
        if (active) setCapabilities(caps)
      })
      .catch(() => {
        /* sem capabilities — UI apenas esconde o toggle */
      })
    return () => {
      active = false
    }
  }, [])

  const handleApplySql = useCallback(
    (sql: string) => {
      onApplyQuery?.(sql)
      recordAiChatMemory(connectionId, sql).catch(() => {
        /* memoria e opcional — falha silenciosa */
      })
    },
    [connectionId, onApplyQuery],
  )

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" })
  }, [messages, streaming])

  const apiMessages = useMemo<AiChatMessage[]>(
    () => messages.map((m) => ({ role: m.role, content: m.content })),
    [messages],
  )

  async function handleSend(overrideInput?: string) {
    const text = (overrideInput ?? input).trim()
    if (!text || streaming) return

    setError("")
    setInput("")

    const userMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
      timestamp: new Date(),
    }

    const assistantMsg: ChatMessage = {
      id: crypto.randomUUID(),
      role: "assistant",
      content: "",
      timestamp: new Date(),
      toolCalls: [],
      reasoning: "",
      deepReasoning,
    }

    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setStreaming(true)

    const messagesForApi: AiChatMessage[] = [
      ...apiMessages,
      { role: "user", content: text },
    ]

    const controller = new AbortController()
    abortRef.current = controller

    await streamAiChat(
      connectionId,
      messagesForApi,
      {
        onMeta: (meta) => {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                reasoningModel: meta.model,
                deepReasoning: meta.reasoning,
              }
            }
            return updated
          })
        },
        onDelta: (delta) => {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = { ...last, content: last.content + delta }
            }
            return updated
          })
        },
        onReasoningDelta: (delta) => {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === "assistant") {
              updated[updated.length - 1] = {
                ...last,
                reasoning: (last.reasoning || "") + delta,
              }
            }
            return updated
          })
        },
        onToolCall: (name) => {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === "assistant") {
              const calls = [...(last.toolCalls || []), { name, status: "calling" as const }]
              updated[updated.length - 1] = { ...last, toolCalls: calls }
            }
            return updated
          })
        },
        onToolResult: (name) => {
          setMessages((prev) => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === "assistant" && last.toolCalls) {
              const calls = last.toolCalls.map((tc) =>
                tc.name === name && tc.status === "calling"
                  ? { ...tc, status: "done" as const }
                  : tc,
              )
              updated[updated.length - 1] = { ...last, toolCalls: calls }
            }
            return updated
          })
        },
        onError: (msg) => {
          setError(msg)
          setStreaming(false)
        },
        onDone: () => {
          setStreaming(false)
        },
      },
      controller.signal,
      { deepReasoning },
    ).catch(() => {
      setStreaming(false)
    })

    abortRef.current = null
    setStreaming(false)
  }

  function handleStop() {
    abortRef.current?.abort()
    abortRef.current = null
    setStreaming(false)
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault()
      void handleSend()
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* Chat Header */}
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <div className="flex items-center gap-2">
          <Sparkles className="size-4 text-primary" />
          <span className="text-xs font-semibold text-foreground">Assistente SQL</span>
        </div>
        <Tooltip text="Fechar chat" side="bottom">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <PanelRightClose className="size-4" />
          </button>
        </Tooltip>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-3">
        {messages.length === 0 ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-center">
            <div className="flex size-12 items-center justify-center rounded-full bg-primary/10">
              <Bot className="size-6 text-primary" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">Assistente SQL</p>
              <p className="mt-1 text-xs text-muted-foreground">
                Pergunte sobre o schema, peca ajuda para construir consultas ou otimizar queries.
              </p>
            </div>
            <div className="mt-2 flex flex-col gap-1.5 w-full">
              {[
                "Quais tabelas existem no banco?",
                "Quais tabelas tem informacao de clientes?",
                "Monte um SELECT com JOIN entre as tabelas principais",
              ].map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => void handleSend(suggestion)}
                  className="rounded-lg border border-border bg-muted/30 px-3 py-2 text-left text-[11px] text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                >
                  {suggestion}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-3">
            {messages.map((msg) => (
              <div key={msg.id}>
                {msg.role === "user" ? (
                  <div className="flex justify-end">
                    <div className="max-w-[85%] rounded-xl bg-primary px-3 py-2 text-[13px] leading-relaxed text-primary-foreground">
                      {msg.content}
                    </div>
                  </div>
                ) : (
                  <div className="text-[13px] leading-relaxed text-foreground">
                    {msg.deepReasoning && (
                      <ReasoningBlock
                        text={msg.reasoning || ""}
                        streaming={
                          streaming &&
                          msg === messages[messages.length - 1] &&
                          !msg.content
                        }
                        model={msg.reasoningModel}
                      />
                    )}
                    {msg.toolCalls && msg.toolCalls.length > 0 && (
                      <div className="mb-2 flex flex-wrap gap-1">
                        {msg.toolCalls.map((tc, i) => (
                          <ToolBadge key={`${tc.name}-${i}`} name={tc.name} status={tc.status} />
                        ))}
                      </div>
                    )}
                    {msg.content ? (
                      <ReactMarkdown
                        remarkPlugins={[remarkGfm]}
                        components={{
                          code({ className, children, ...props }) {
                            const isBlock = className?.startsWith("language-")
                            if (isBlock) {
                              return (
                                <CodeBlock className={className} onApply={handleApplySql}>
                                  {children}
                                </CodeBlock>
                              )
                            }
                            return (
                              <code
                                className="rounded bg-muted px-1 py-0.5 font-mono text-[12px]"
                                {...props}
                              >
                                {children}
                              </code>
                            )
                          },
                          pre({ children }) {
                            return <>{children}</>
                          },
                          p({ children }) {
                            return <p className="mb-2 last:mb-0">{children}</p>
                          },
                          ul({ children }) {
                            return <ul className="mb-2 ml-4 list-disc space-y-0.5">{children}</ul>
                          },
                          ol({ children }) {
                            return <ol className="mb-2 ml-4 list-decimal space-y-0.5">{children}</ol>
                          },
                          table({ children }) {
                            return (
                              <div className="my-2 overflow-x-auto rounded border border-border">
                                <table className="w-full text-[11px]">{children}</table>
                              </div>
                            )
                          },
                          th({ children }) {
                            return <th className="border-b border-border bg-muted px-2 py-1 text-left font-semibold">{children}</th>
                          },
                          td({ children }) {
                            return <td className="border-b border-border/50 px-2 py-1">{children}</td>
                          },
                        }}
                      >
                        {msg.content}
                      </ReactMarkdown>
                    ) : streaming && msg === messages[messages.length - 1] ? (
                      <div className="flex items-center gap-1.5 rounded-xl bg-muted px-3 py-2">
                        <div className="size-1.5 animate-bounce rounded-full bg-muted-foreground/40" style={{ animationDelay: "0ms" }} />
                        <div className="size-1.5 animate-bounce rounded-full bg-muted-foreground/40" style={{ animationDelay: "150ms" }} />
                        <div className="size-1.5 animate-bounce rounded-full bg-muted-foreground/40" style={{ animationDelay: "300ms" }} />
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            ))}
            <div ref={messagesEndRef} />
          </div>
        )}

        {error && (
          <div className="mt-2 rounded-lg border border-red-500/20 bg-red-500/10 px-3 py-2 text-[12px] text-red-600 dark:text-red-400">
            {error}
          </div>
        )}
      </div>

      {/* Input */}
      <div className="border-t border-border p-3">
        <div className="flex items-center gap-2 rounded-xl border border-input bg-background px-3 py-2.5">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={deepReasoning ? "Pergunta complexa..." : "Pergunte algo..."}
            rows={1}
            className="flex-1 resize-none bg-transparent text-[13px] leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
            style={{ maxHeight: 80 }}
            onInput={(e) => {
              const el = e.currentTarget
              el.style.height = "auto"
              el.style.height = Math.min(el.scrollHeight, 80) + "px"
            }}
          />
          {capabilities?.reasoning_enabled && (
            <Tooltip
              text={
                deepReasoning
                  ? "Raciocinio profundo ATIVO (mais lento, melhor em queries complexas)"
                  : "Ativar raciocinio profundo"
              }
              side="top"
            >
              <button
                type="button"
                onClick={() => setDeepReasoning((v) => !v)}
                disabled={streaming}
                className={`shrink-0 rounded-md p-1 transition-colors disabled:opacity-50 ${
                  deepReasoning
                    ? "bg-primary/15 text-primary hover:bg-primary/25"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`}
              >
                <Brain className="size-4" />
              </button>
            </Tooltip>
          )}
          {streaming ? (
            <button
              type="button"
              onClick={handleStop}
              className="shrink-0 rounded-md p-1 text-destructive transition-colors hover:bg-destructive/10"
            >
              <Square className="size-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={() => void handleSend()}
              disabled={!input.trim()}
              className="shrink-0 rounded-md p-1 text-primary transition-colors hover:bg-primary/10 disabled:text-muted-foreground disabled:opacity-50"
            >
              <SendHorizontal className="size-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
