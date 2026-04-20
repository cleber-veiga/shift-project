"use client"

import { useCallback, useMemo } from "react"
import {
  getValidSession,
  type AuthSession,
} from "@/lib/auth"
import type {
  AgentThreadSummary,
  AgentThreadDetail,
  AgentMessage,
  ProposedPlan,
  RawProposedPlan,
} from "@/lib/types/ai-panel"
import { convertRawPlan } from "@/lib/types/ai-panel"

function getApiBaseUrl() {
  const value = process.env.NEXT_PUBLIC_API_BASE_URL
  return value && value.trim().length > 0 ? value.trim() : "http://localhost:8000/api/v1"
}

function dispatchSessionExpired() {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event("auth:session-expired"))
  }
}

async function getSession(): Promise<AuthSession> {
  const session = await getValidSession()
  if (!session) {
    dispatchSessionExpired()
    throw new Error("Sessao expirada. Faca login novamente.")
  }
  return session
}

function authHeaders(session: AuthSession): HeadersInit {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${session.accessToken}`,
  }
}

// Converte a resposta raw do backend (snake_case) para AgentMessage (camelCase)
function convertMessage(raw: RawAgentMessage): AgentMessage {
  return {
    id: raw.id,
    role: raw.role as AgentMessage["role"],
    content: raw.content,
    toolName: raw.tool_name ?? undefined,
    createdAt: raw.created_at,
  }
}

interface RawAgentMessage {
  id: string
  role: string
  content: string | null
  tool_name?: string | null
  tool_calls?: unknown[] | null
  created_at: string
}

interface RawPendingApproval {
  id: string
  status: string
  proposed_plan: RawProposedPlan
  expires_at: string
}

interface RawThreadSummary {
  id: string
  title: string | null
  status: string
  created_at: string
  updated_at: string
}

interface RawThreadDetail extends RawThreadSummary {
  messages: RawAgentMessage[]
  pending_approval: RawPendingApproval | null
}

function convertThreadSummary(raw: RawThreadSummary): AgentThreadSummary {
  return {
    id: raw.id,
    title: raw.title,
    status: raw.status as AgentThreadSummary["status"],
    createdAt: raw.created_at,
    updatedAt: raw.updated_at,
  }
}

function convertPendingApproval(
  raw: RawPendingApproval,
): AgentThreadDetail["pendingApproval"] {
  return {
    id: raw.id,
    proposedPlan: convertRawPlan(raw.proposed_plan),
    expiresAt: raw.expires_at,
  }
}

function convertThreadDetail(raw: RawThreadDetail): AgentThreadDetail {
  const messages = raw.messages.map(convertMessage)
  const pendingApproval = raw.pending_approval
    ? convertPendingApproval(raw.pending_approval)
    : null

  // Se ha aprovacao pendente, injeta um estado sintetico na ultima mensagem
  // de assistente que possa conter o plano, para que o card mostre os botoes.
  if (pendingApproval) {
    const lastAssistantIdx = messages.map((m) => m.role).lastIndexOf("assistant")
    if (lastAssistantIdx >= 0) {
      messages[lastAssistantIdx] = {
        ...messages[lastAssistantIdx],
        planProposed: pendingApproval.proposedPlan as ProposedPlan,
        approvalId: pendingApproval.id,
        approvalStatus: "pending",
      }
    }
  }

  return {
    ...convertThreadSummary(raw),
    messages,
    pendingApproval,
  }
}

async function parseError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string }
    if (typeof data.detail === "string" && data.detail.trim()) return data.detail
  } catch { /* ignora */ }
  return `Erro na requisicao (${response.status}).`
}

export function useAgentApi() {
  const listThreads = useCallback(async (workspaceId: string): Promise<AgentThreadSummary[]> => {
    const session = await getSession()
    const response = await fetch(
      `${getApiBaseUrl()}/agent/threads?workspace_id=${workspaceId}&limit=50`,
      { method: "GET", headers: authHeaders(session) },
    )
    if (response.status === 401) { dispatchSessionExpired(); throw new Error("Sessao expirada.") }
    if (!response.ok) throw new Error(await parseError(response))
    const data = (await response.json()) as RawThreadSummary[]
    return data.map(convertThreadSummary)
  }, [])

  const getThread = useCallback(async (threadId: string): Promise<AgentThreadDetail> => {
    const session = await getSession()
    const response = await fetch(
      `${getApiBaseUrl()}/agent/threads/${threadId}`,
      { method: "GET", headers: authHeaders(session) },
    )
    if (response.status === 401) { dispatchSessionExpired(); throw new Error("Sessao expirada.") }
    if (!response.ok) throw new Error(await parseError(response))
    const data = (await response.json()) as RawThreadDetail
    return convertThreadDetail(data)
  }, [])

  const deleteThread = useCallback(async (threadId: string): Promise<void> => {
    const session = await getSession()
    const response = await fetch(
      `${getApiBaseUrl()}/agent/threads/${threadId}`,
      { method: "DELETE", headers: authHeaders(session) },
    )
    if (response.status === 401) { dispatchSessionExpired(); throw new Error("Sessao expirada.") }
    if (!response.ok) throw new Error(await parseError(response))
  }, [])

  const streamCreateThread = useCallback(async (
    params: {
      workspaceId: string
      projectId: string | null
      screenContext: unknown
      initialMessage: string
    },
    signal: AbortSignal,
  ): Promise<Response> => {
    const session = await getSession()
    return fetch(`${getApiBaseUrl()}/agent/threads`, {
      method: "POST",
      headers: { ...authHeaders(session), Accept: "text/event-stream" },
      body: JSON.stringify({
        workspace_id: params.workspaceId,
        project_id: params.projectId,
        screen_context: params.screenContext,
        initial_message: params.initialMessage,
      }),
      signal,
    })
  }, [])

  const streamSendMessage = useCallback(async (
    threadId: string,
    message: string,
    screenContext: unknown,
    signal: AbortSignal,
  ): Promise<Response> => {
    const session = await getSession()
    return fetch(`${getApiBaseUrl()}/agent/threads/${threadId}/messages`, {
      method: "POST",
      headers: { ...authHeaders(session), Accept: "text/event-stream" },
      body: JSON.stringify({ message, screen_context: screenContext }),
      signal,
    })
  }, [])

  const streamApprove = useCallback(async (
    threadId: string,
    approvalId: string,
    signal: AbortSignal,
  ): Promise<Response> => {
    const session = await getSession()
    return fetch(`${getApiBaseUrl()}/agent/threads/${threadId}/approve`, {
      method: "POST",
      headers: { ...authHeaders(session), Accept: "text/event-stream" },
      body: JSON.stringify({ approval_id: approvalId }),
      signal,
    })
  }, [])

  const streamReject = useCallback(async (
    threadId: string,
    approvalId: string,
    reason: string | undefined,
    signal: AbortSignal,
  ): Promise<Response> => {
    const session = await getSession()
    return fetch(`${getApiBaseUrl()}/agent/threads/${threadId}/reject`, {
      method: "POST",
      headers: { ...authHeaders(session), Accept: "text/event-stream" },
      body: JSON.stringify({ approval_id: approvalId, reason: reason ?? null }),
      signal,
    })
  }, [])

  return useMemo(() => ({
    listThreads,
    getThread,
    deleteThread,
    streamCreateThread,
    streamSendMessage,
    streamApprove,
    streamReject,
  }), [deleteThread, getThread, listThreads, streamApprove, streamCreateThread, streamReject, streamSendMessage])
}
