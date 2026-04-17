// Cliente HTTP para WorkflowVersions e picker de workflows callable.
// Consumido pelos nós call_workflow, loop e pelo IoSchemaEditor no editor.

import { authorizedRequest } from "@/lib/auth"

export type WorkflowParamType =
  | "string"
  | "integer"
  | "number"
  | "boolean"
  | "object"
  | "array"
  | "table_reference"

export const WORKFLOW_PARAM_TYPES: WorkflowParamType[] = [
  "string",
  "integer",
  "number",
  "boolean",
  "object",
  "array",
  "table_reference",
]

export interface WorkflowParam {
  name: string
  type: WorkflowParamType
  required?: boolean
  default?: unknown
  description?: string | null
}

export interface CallableWorkflowSummary {
  workflow_id: string
  name: string
  description: string | null
  versions: number[]
  latest_version: number
}

export interface WorkflowIOSchema {
  inputs: WorkflowParam[]
  outputs: WorkflowParam[]
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

export interface PublishWorkflowVersionBody {
  io_schema: WorkflowIOSchema
  definition?: Record<string, unknown> | null
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

export async function publishWorkflowVersion(
  workflowId: string,
  body: PublishWorkflowVersionBody,
): Promise<WorkflowVersionResponse> {
  return authorizedRequest<WorkflowVersionResponse>(
    `/workflows/${workflowId}/versions`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  )
}
