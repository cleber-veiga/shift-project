// Cliente HTTP para WorkflowVersions e picker de workflows callable.
// Consumido pelos nos call_workflow e loop no editor.

import { authorizedRequest } from "@/lib/auth"

export interface WorkflowParam {
  name: string
  type: "string" | "number" | "boolean" | "object" | "array"
  required?: boolean
  default?: unknown
  description?: string
}

export interface CallableWorkflowSummary {
  workflow_id: string
  name: string
  description: string | null
  versions: number[]
  latest_version: number
}

export interface WorkflowVersionResponse {
  id: string
  workflow_id: string
  version: number
  input_schema: WorkflowParam[]
  output_schema: WorkflowParam[]
  published: boolean
  created_at: string
}

export async function listCallableWorkflows(): Promise<CallableWorkflowSummary[]> {
  return authorizedRequest<CallableWorkflowSummary[]>(
    `/workflows/callable`,
    { method: "GET" },
  )
}

export async function listWorkflowVersions(
  workflowId: string,
): Promise<WorkflowVersionResponse[]> {
  return authorizedRequest<WorkflowVersionResponse[]>(
    `/workflows/${workflowId}/versions`,
    { method: "GET" },
  )
}
