import { authorizedRequest, getValidSession } from "@/lib/auth"
import type { WorkflowVariable } from "@/lib/workflow/types"

export interface ConnectionOption {
  id: string
  name: string
  type: string
}

export interface InheritedVariable {
  variable: WorkflowVariable
  sub_workflow_id: string
  sub_workflow_name: string
  sub_workflow_version: number
}

export interface VariablesSchemaResponse {
  variables: WorkflowVariable[]
  connection_options: Record<string, ConnectionOption[]>
  inherited_variables: InheritedVariable[]
}

export async function getWorkflowVariables(workflowId: string): Promise<WorkflowVariable[]> {
  return authorizedRequest<WorkflowVariable[]>(
    `/workflows/${workflowId}/variables`,
    { method: "GET" },
  )
}

export async function updateWorkflowVariables(
  workflowId: string,
  variables: WorkflowVariable[],
): Promise<WorkflowVariable[]> {
  return authorizedRequest<WorkflowVariable[]>(
    `/workflows/${workflowId}/variables`,
    {
      method: "PUT",
      body: JSON.stringify({ variables }),
    },
  )
}

export async function getVariablesSchema(workflowId: string): Promise<VariablesSchemaResponse> {
  return authorizedRequest<VariablesSchemaResponse>(
    `/workflows/${workflowId}/variables/schema`,
    { method: "GET" },
  )
}

export type WorkflowRunMode = "full" | "preview" | "validate"

export interface ExecuteWorkflowOptions {
  variableValues?: Record<string, unknown>
  retryFromExecutionId?: string
  runMode?: WorkflowRunMode
}

export interface ValidateConnectionResult {
  connection_id: string
  name: string
  ok: boolean
  error: string | null
}

export interface ValidateExecutionResponse {
  ok: boolean
  connections: ValidateConnectionResult[]
  missing_variables: string[]
  errors: string[]
}

export async function executeWorkflowWithVars(
  workflowId: string,
  variableValues: Record<string, unknown>,
): Promise<{ execution_id: string }> {
  return authorizedRequest<{ execution_id: string }>(
    `/workflows/${workflowId}/execute`,
    {
      method: "POST",
      body: JSON.stringify({ variable_values: variableValues }),
    },
  )
}

/**
 * Dispara uma execucao com controle de ``run_mode`` e retry.
 *
 * - ``run_mode=validate`` e sincrono: retorna ``ValidateExecutionResponse``.
 * - ``run_mode=preview|full`` retorna ``{ execution_id }`` (202).
 */
export async function executeWorkflow(
  workflowId: string,
  options: ExecuteWorkflowOptions = {},
): Promise<{ execution_id: string } | ValidateExecutionResponse> {
  const body: Record<string, unknown> = {
    variable_values: options.variableValues ?? {},
  }
  if (options.retryFromExecutionId) {
    body.retry_from_execution_id = options.retryFromExecutionId
  }
  if (options.runMode) {
    body.run_mode = options.runMode
  }
  return authorizedRequest(
    `/workflows/${workflowId}/execute`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  )
}

export async function uploadWorkflowFile(
  workflowId: string,
  file: File,
  onProgress?: (percent: number) => void,
): Promise<{ file_id: string; filename: string }> {
  const session = await getValidSession()
  if (!session) throw new Error("Sessão expirada.")

  const baseUrl =
    (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").trim() ||
    "http://localhost:8000/api/v1"

  const formData = new FormData()
  formData.append("file", file)

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()

    if (onProgress) {
      xhr.upload.addEventListener("progress", (e) => {
        if (e.lengthComputable) onProgress(Math.round((e.loaded / e.total) * 100))
      })
    }

    xhr.addEventListener("load", () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          resolve(JSON.parse(xhr.responseText) as { file_id: string; filename: string })
        } catch {
          reject(new Error("Resposta inválida do servidor"))
        }
      } else {
        reject(new Error(xhr.responseText || `Erro no upload (${xhr.status})`))
      }
    })
    xhr.addEventListener("error", () => reject(new Error("Falha na conexão durante o upload")))
    xhr.addEventListener("abort", () => reject(new Error("Upload cancelado")))

    xhr.open("POST", `${baseUrl}/workflows/${workflowId}/uploads`)
    xhr.setRequestHeader("Authorization", `Bearer ${session.accessToken}`)
    xhr.send(formData)
  })
}
