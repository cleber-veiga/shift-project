// Cliente HTTP da aba "Executions" do editor de workflows.
// Centraliza tipos e chamadas para os endpoints de listagem, detalhe,
// cancelamento e exclusao de execucoes.

import { authorizedRequest } from "@/lib/auth"

export type ExecutionStatus =
  | "PENDING"
  | "RUNNING"
  | "SUCCESS"
  | "COMPLETED"
  | "FAILED"
  | "CANCELLED"
  | "ABORTED"
  | "CRASHED"

export type TriggeredBy = "manual" | "cron" | "api" | "webhook"

export interface ExecutionSummary {
  id: string
  workflow_id: string
  status: ExecutionStatus
  triggered_by: TriggeredBy
  duration_ms: number | null
  started_at: string | null
  completed_at: string | null
  node_count: number
  error_message: string | null
}

export interface ExecutionListResponse {
  items: ExecutionSummary[]
  total: number
  page: number
  size: number
}

export interface NodeExecution {
  id: string
  execution_id: string
  node_id: string
  node_type: string
  label: string | null
  status: "running" | "success" | "error" | "skipped"
  duration_ms: number
  row_count_in: number | null
  row_count_out: number | null
  output_summary: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
}

export interface ExecutionDetail {
  execution_id: string
  status: ExecutionStatus
  triggered_by: TriggeredBy
  result: Record<string, unknown> | null
  error_message: string | null
  started_at: string | null
  completed_at: string | null
  nodes: NodeExecution[]
  input_data?: { variable_values?: Record<string, unknown> } | null
}

export interface ListExecutionsParams {
  workflowId: string
  status?: ExecutionStatus
  triggered_by?: TriggeredBy
  from?: string
  to?: string
  page?: number
  size?: number
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const entries: [string, string][] = []
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null || value === "") continue
    entries.push([key, String(value)])
  }
  if (entries.length === 0) return ""
  const qs = new URLSearchParams(entries).toString()
  return `?${qs}`
}

export async function listExecutions(
  params: ListExecutionsParams,
): Promise<ExecutionListResponse> {
  const { workflowId, ...rest } = params
  const qs = buildQuery(rest)
  return authorizedRequest<ExecutionListResponse>(
    `/workflows/${workflowId}/executions${qs}`,
    { method: "GET" },
  )
}

export async function getExecutionDetail(
  executionId: string,
): Promise<ExecutionDetail> {
  return authorizedRequest<ExecutionDetail>(
    `/workflows/executions/${executionId}/details`,
    { method: "GET" },
  )
}

export async function cancelExecution(executionId: string): Promise<void> {
  await authorizedRequest<unknown>(
    `/workflows/executions/${executionId}/cancel`,
    { method: "POST" },
  )
}

export async function deleteExecution(executionId: string): Promise<void> {
  await authorizedRequest<unknown>(
    `/workflows/executions/${executionId}`,
    { method: "DELETE" },
  )
}
