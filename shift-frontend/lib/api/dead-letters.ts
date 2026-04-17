// Cliente HTTP da aba/pagina "Dead Letters".
// Lista entradas e dispara retry manual.

import { authorizedRequest } from "@/lib/auth"

export interface DeadLetterItem {
  id: string
  execution_id: string
  workflow_id: string
  node_id: string
  error_message: string
  payload: Record<string, unknown>
  retry_count: number
  created_at: string
  resolved_at: string | null
}

export interface DeadLetterListResponse {
  items: DeadLetterItem[]
  total: number
  page: number
  size: number
}

export interface DeadLetterRetryResponse {
  dead_letter_id: string
  resolved: boolean
  retry_count: number
  status: string
  message: string | null
  output: Record<string, unknown> | null
}

export interface ListDeadLettersParams {
  workspaceId: string
  workflowId?: string
  executionId?: string
  includeResolved?: boolean
  page?: number
  size?: number
}

function buildQuery(params: Record<string, string | number | boolean | undefined>): string {
  const entries: [string, string][] = []
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    entries.push([key, String(value)])
  }
  if (entries.length === 0) return ""
  return `?${new URLSearchParams(entries).toString()}`
}

export async function listDeadLetters(
  params: ListDeadLettersParams,
): Promise<DeadLetterListResponse> {
  const qs = buildQuery({
    workspace_id: params.workspaceId,
    workflow_id: params.workflowId,
    execution_id: params.executionId,
    include_resolved: params.includeResolved,
    page: params.page,
    size: params.size,
  })
  return authorizedRequest<DeadLetterListResponse>(`/dead-letters${qs}`, {
    method: "GET",
  })
}

export async function retryDeadLetter(id: string): Promise<DeadLetterRetryResponse> {
  return authorizedRequest<DeadLetterRetryResponse>(
    `/dead-letters/${id}/retry`,
    { method: "POST" },
  )
}
