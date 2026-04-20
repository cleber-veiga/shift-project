"use client"

import { useCallback, useEffect, useReducer, useRef, useState } from "react"
import type { AgentMessage, AgentSSEEvent, ExecutedToolCall } from "@/lib/types/ai-panel"
import { convertRawPlan } from "@/lib/types/ai-panel"
import { useAgentApi } from "@/lib/hooks/use-agent-api"
import { useAIPanelContext } from "@/lib/context/ai-panel-context"
import { useDashboard } from "@/lib/context/dashboard-context"

// ID sentinela para a mensagem em streaming ativo
const STREAMING_ID = "streaming-current"

// ─── Parser SSE ───────────────────────────────────────────────────────────────

function parseSSEEvent(chunk: string): AgentSSEEvent | null {
  const lines = chunk.split("\n")
  let eventType: string | null = null
  let dataRaw: string | null = null
  for (const line of lines) {
    if (line.startsWith("event:")) eventType = line.slice(6).trim()
    else if (line.startsWith("data:")) dataRaw = line.slice(5).trim()
  }
  if (!eventType || dataRaw === null) return null
  try {
    return { type: eventType, data: JSON.parse(dataRaw) } as AgentSSEEvent
  } catch {
    return null
  }
}

export async function consumeSSEStream(
  response: Response,
  onEvent: (event: AgentSSEEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  if (!response.body) throw new Error("Stream sem body")

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  try {
    while (true) {
      if (signal.aborted) { await reader.cancel(); break }
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })

      // Eventos SSE separados por \n\n; ultimo fragmento pode ser incompleto
      const parts = buffer.split("\n\n")
      buffer = parts.pop() ?? ""

      for (const part of parts) {
        if (!part.trim()) continue
        const parsed = parseSSEEvent(part)
        if (parsed) onEvent(parsed)
      }
    }
  } finally {
    reader.releaseLock()
  }
}

// ─── Reducer de mensagens ─────────────────────────────────────────────────────

type MessageAction =
  | { type: "RESET" }
  | { type: "LOAD"; payload: AgentMessage[] }
  | { type: "ADD_USER"; payload: { id: string; content: string } }
  | { type: "START_ASSISTANT_STREAM"; payload?: { thinkingNode?: string } }
  | { type: "MARK_USER_FAILED"; payload: string }
  | { type: "APPLY_EVENT"; payload: AgentSSEEvent }
  | { type: "APPROVE_PLAN"; payload: { approvalId: string } }
  | { type: "REJECT_PLAN"; payload: { approvalId: string; reason?: string } }

function applyEventToStreaming(msg: AgentMessage, event: AgentSSEEvent): AgentMessage {
  switch (event.type) {
    case "thinking":
      return { ...msg, thinkingNode: event.data.node }

    case "guardrails_refuse":
      return { ...msg, thinkingNode: undefined, content: event.data.reason, isGuardrailsRefusal: true }

    case "plan_proposed":
      return {
        ...msg,
        thinkingNode: undefined,
        planProposed: convertRawPlan(event.data.plan),
      }

    case "approval_required":
      return {
        ...msg,
        approvalId: event.data.approval_id,
        approvalStatus: "pending",
        planProposed: msg.planProposed ?? convertRawPlan(event.data.plan),
      }

    case "tool_call_start": {
      const existing = msg.toolCallsExecuted ?? []
      const entry: ExecutedToolCall = {
        step: event.data.step,
        toolName: event.data.tool_name,
        success: false,
        preview: "",
        durationMs: 0,
        running: true,
      }
      const updated = existing.filter((t) => t.step !== event.data.step)
      return { ...msg, thinkingNode: undefined, toolCallsExecuted: [...updated, entry] }
    }

    case "tool_call_end": {
      const existing = msg.toolCallsExecuted ?? []
      const entry: ExecutedToolCall = {
        step: event.data.step,
        toolName: event.data.tool_name,
        success: event.data.success,
        preview: event.data.preview,
        durationMs: event.data.duration_ms,
        error: event.data.error,
        running: false,
      }
      return {
        ...msg,
        toolCallsExecuted: existing.map((t) => (t.step === event.data.step ? entry : t)),
      }
    }

    case "delta":
      return { ...msg, thinkingNode: undefined, content: (msg.content ?? "") + event.data.text }

    default:
      return msg
  }
}

function messageReducer(state: AgentMessage[], action: MessageAction): AgentMessage[] {
  switch (action.type) {
    case "RESET":
      return []

    case "LOAD":
      return action.payload

    case "ADD_USER":
      return [
        ...state,
        {
          id: action.payload.id,
          role: "user",
          content: action.payload.content,
          createdAt: new Date().toISOString(),
        },
      ]

    case "START_ASSISTANT_STREAM":
      if (state.some((m) => m.id === STREAMING_ID)) return state
      return [
        ...state,
        {
          id: STREAMING_ID,
          role: "assistant",
          content: null,
          createdAt: new Date().toISOString(),
          isStreaming: true,
          thinkingNode: action.payload?.thinkingNode,
        },
      ]

    case "MARK_USER_FAILED":
      return state.map((m) => (m.id === action.payload ? { ...m, failed: true } : m))

    case "APPROVE_PLAN":
      return state.map((m) =>
        m.approvalId === action.payload.approvalId
          ? { ...m, approvalStatus: "approved" as const }
          : m,
      )

    case "REJECT_PLAN":
      return state.map((m) =>
        m.approvalId === action.payload.approvalId
          ? {
              ...m,
              approvalStatus: "rejected" as const,
              approvalRejectedReason: action.payload.reason,
            }
          : m,
      )

    case "APPLY_EVENT": {
      const event = action.payload
      const streamingIdx = state.findIndex((m) => m.id === STREAMING_ID)

      if (event.type === "done") {
        if (streamingIdx === -1) return state
        return state.map((m, i) =>
          i === streamingIdx
            ? { ...m, id: `msg-${Date.now()}`, isStreaming: false }
            : m,
        )
      }

      if (event.type === "error") {
        const errMsg: AgentMessage = {
          id: `err-${Date.now()}`,
          role: "assistant",
          content: event.data.message,
          createdAt: new Date().toISOString(),
          isStreaming: false,
        }
        if (streamingIdx === -1) return [...state, errMsg]
        return [
          ...state.filter((m) => m.id !== STREAMING_ID),
          errMsg,
        ]
      }

      // Cria mensagem streaming se nao existe
      if (streamingIdx === -1) {
        const newMsg: AgentMessage = {
          id: STREAMING_ID,
          role: "assistant",
          content: null,
          createdAt: new Date().toISOString(),
          isStreaming: true,
        }
        return [...state, applyEventToStreaming(newMsg, event)]
      }

      return state.map((m, i) =>
        i === streamingIdx ? applyEventToStreaming(m, event) : m,
      )
    }

    default:
      return state
  }
}

// ─── Hook principal ───────────────────────────────────────────────────────────

export interface RateLimitInfo {
  message: string
  retryAfterSeconds: number
}

export interface UseAIStreamResult {
  messages: AgentMessage[]
  isStreaming: boolean
  currentThinking: string | null
  error: string | null
  rateLimit: RateLimitInfo | null
  sendMessage: (message: string, screenContext: unknown) => Promise<void>
  approve: (approvalId: string) => Promise<void>
  reject: (approvalId: string, reason?: string) => Promise<void>
  clearError: () => void
  clearRateLimit: () => void
}

export function useAIStream(): UseAIStreamResult {
  const { activeThreadId, setActiveThread } = useAIPanelContext()
  const { selectedWorkspace, selectedProject } = useDashboard()
  const api = useAgentApi()

  const [messages, dispatch] = useReducer(messageReducer, [])
  const [isStreaming, setIsStreaming] = useState(false)
  const [currentThinking, setCurrentThinking] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [rateLimit, setRateLimit] = useState<RateLimitInfo | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const isStreamingRef = useRef(false)
  const threadIdRef = useRef<string | null>(activeThreadId)
  isStreamingRef.current = isStreaming
  threadIdRef.current = activeThreadId

  // Carrega thread quando activeThreadId muda
  useEffect(() => {
    if (isStreamingRef.current) {
      return
    }

    abortRef.current?.abort()

    if (!activeThreadId) {
      dispatch({ type: "RESET" })
      setIsStreaming(false)
      setCurrentThinking(null)
      setError(null)
      return
    }

    let cancelled = false

    void api.getThread(activeThreadId).then((thread) => {
      if (cancelled) return
      dispatch({ type: "LOAD", payload: thread.messages })
    }).catch((err: unknown) => {
      if (cancelled) return
      const msg = err instanceof Error ? err.message : "Erro ao carregar conversa."
      setError(msg)
    })

    return () => { cancelled = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeThreadId])

  // Abort no unmount
  useEffect(() => {
    return () => { abortRef.current?.abort() }
  }, [])

  const runStream = useCallback(async (
    getResponse: (signal: AbortSignal) => Promise<Response>,
    tempUserId?: string,
  ) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setIsStreaming(true)
    setCurrentThinking("starting")
    setError(null)
    dispatch({ type: "START_ASSISTANT_STREAM", payload: { thinkingNode: "starting" } })

    try {
      const response = await getResponse(controller.signal)

      if (controller.signal.aborted) return

      if (!response.ok) {
        let detail = `Erro ${response.status}`
        try {
          const data = (await response.json()) as { detail?: string }
          if (data.detail) detail = data.detail
        } catch { /* ignora */ }
        if (response.status === 429) {
          const headerValue = response.headers.get("Retry-After")
          const parsed = headerValue ? parseInt(headerValue, 10) : NaN
          const retryAfterSeconds = Number.isFinite(parsed) && parsed > 0 ? parsed : 60
          setRateLimit({ message: detail, retryAfterSeconds })
        }
        throw new Error(detail)
      }

      await consumeSSEStream(
        response,
        (event) => {
          if (event.type === "thread_created") {
            setActiveThread(event.data.thread_id)
            return
          }
          if (event.type === "thinking") {
            setCurrentThinking(event.data.node)
          }
          if (event.type === "done" || event.type === "error") {
            setIsStreaming(false)
            setCurrentThinking(null)
          }
          dispatch({ type: "APPLY_EVENT", payload: event })
        },
        controller.signal,
      )
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return
      const msg = err instanceof Error ? err.message : "Falha na conexao."
      setError(msg)
      if (tempUserId) dispatch({ type: "MARK_USER_FAILED", payload: tempUserId })
    } finally {
      if (!controller.signal.aborted) {
        setIsStreaming(false)
        setCurrentThinking(null)
      }
    }
  }, [setActiveThread])

  const sendMessage = useCallback(async (message: string, screenContext: unknown) => {
    if (isStreaming) return

    const tempId = `temp-user-${Date.now()}`
    dispatch({ type: "ADD_USER", payload: { id: tempId, content: message } })

    await runStream(async (signal) => {
      const tid = threadIdRef.current
      if (!tid) {
        const workspaceId = selectedWorkspace?.id
        if (!workspaceId) throw new Error("Selecione um workspace primeiro.")
        return api.streamCreateThread(
          {
            workspaceId,
            projectId: selectedProject?.id ?? null,
            screenContext,
            initialMessage: message,
          },
          signal,
        )
      }
      return api.streamSendMessage(tid, message, screenContext, signal)
    }, tempId)
  }, [isStreaming, runStream, selectedWorkspace, selectedProject, api])

  const approve = useCallback(async (approvalId: string) => {
    if (isStreaming) return
    const tid = threadIdRef.current
    if (!tid) return

    dispatch({ type: "APPROVE_PLAN", payload: { approvalId } })

    await runStream((signal) => api.streamApprove(tid, approvalId, signal))
  }, [isStreaming, runStream, api])

  const reject = useCallback(async (approvalId: string, reason?: string) => {
    if (isStreaming) return
    const tid = threadIdRef.current
    if (!tid) return

    dispatch({ type: "REJECT_PLAN", payload: { approvalId, reason } })

    await runStream((signal) => api.streamReject(tid, approvalId, reason, signal))
  }, [isStreaming, runStream, api])

  const clearError = useCallback(() => setError(null), [])
  const clearRateLimit = useCallback(() => setRateLimit(null), [])

  return {
    messages,
    isStreaming,
    currentThinking,
    error,
    rateLimit,
    sendMessage,
    approve,
    reject,
    clearError,
    clearRateLimit,
  }
}
