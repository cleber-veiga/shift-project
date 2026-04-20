"use client"

import { useCallback, useMemo } from "react"
import { getValidSession, type AuthSession } from "@/lib/auth"

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

async function parseError(response: Response): Promise<string> {
  try {
    const data = (await response.json()) as { detail?: string }
    if (typeof data.detail === "string" && data.detail.trim()) return data.detail
  } catch { /* ignora */ }
  return `Erro na requisicao (${response.status}).`
}

export interface AuditEntry {
  id: string
  thread_id: string
  approval_id: string | null
  user_id: string
  tool_name: string
  status: "success" | "error"
  duration_ms: number | null
  error_message: string | null
  created_at: string
}

export interface AuditEntryDetail extends AuditEntry {
  tool_arguments: Record<string, unknown>
  tool_result_preview: string | null
  log_metadata: Record<string, unknown> | null
}

export interface AuditListResult {
  items: AuditEntry[]
  total: number
  limit: number
  offset: number
}

export interface AuditStats {
  total_executions: number
  successful_executions: number
  failed_executions: number
  success_rate: number
  top_tools: { tool_name: string; count: number }[]
  top_users: { user_id: string; count: number }[]
}

export interface AuditListParams {
  workspaceId: string
  projectId?: string | null
  userId?: string | null
  toolName?: string | null
  status?: "success" | "error" | null
  fromDate?: string | null
  toDate?: string | null
  limit?: number
  offset?: number
}

function buildQuery(params: Record<string, unknown>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === "") continue
    search.append(key, String(value))
  }
  const qs = search.toString()
  return qs ? `?${qs}` : ""
}

export function useAgentAudit() {
  const list = useCallback(async (params: AuditListParams): Promise<AuditListResult> => {
    const session = await getSession()
    const qs = buildQuery({
      workspace_id: params.workspaceId,
      project_id: params.projectId ?? undefined,
      user_id: params.userId ?? undefined,
      tool_name: params.toolName ?? undefined,
      status: params.status ?? undefined,
      from_date: params.fromDate ?? undefined,
      to_date: params.toDate ?? undefined,
      limit: params.limit ?? 50,
      offset: params.offset ?? 0,
    })
    const response = await fetch(`${getApiBaseUrl()}/agent/audit/${qs}`, {
      method: "GET",
      headers: authHeaders(session),
    })
    if (response.status === 401) { dispatchSessionExpired(); throw new Error("Sessao expirada.") }
    if (!response.ok) throw new Error(await parseError(response))
    return (await response.json()) as AuditListResult
  }, [])

  const stats = useCallback(async (workspaceId: string, projectId?: string | null, days = 30): Promise<AuditStats> => {
    const session = await getSession()
    const qs = buildQuery({
      workspace_id: workspaceId,
      project_id: projectId ?? undefined,
      days,
    })
    const response = await fetch(`${getApiBaseUrl()}/agent/audit/stats${qs}`, {
      method: "GET",
      headers: authHeaders(session),
    })
    if (response.status === 401) { dispatchSessionExpired(); throw new Error("Sessao expirada.") }
    if (!response.ok) throw new Error(await parseError(response))
    return (await response.json()) as AuditStats
  }, [])

  const getEntry = useCallback(async (entryId: string, workspaceId: string): Promise<AuditEntryDetail> => {
    const session = await getSession()
    const qs = buildQuery({ workspace_id: workspaceId })
    const response = await fetch(`${getApiBaseUrl()}/agent/audit/${entryId}${qs}`, {
      method: "GET",
      headers: authHeaders(session),
    })
    if (response.status === 401) { dispatchSessionExpired(); throw new Error("Sessao expirada.") }
    if (!response.ok) throw new Error(await parseError(response))
    return (await response.json()) as AuditEntryDetail
  }, [])

  return useMemo(() => ({ list, stats, getEntry }), [getEntry, list, stats])
}
