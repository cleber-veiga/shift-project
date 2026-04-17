// Cliente HTTP para o no Webhook do editor de workflows.
// Cobre resolucao das URLs (test/producao), escuta por captura de teste
// ("Listen for test event") e limpeza do buffer de capturas.

import { authorizedRequest } from "@/lib/auth"

export interface WebhookUrls {
  node_id: string | null
  http_method: string
  path: string
  test_url: string
  production_url: string
  production_ready: boolean
}

export interface WebhookCapture {
  id: string
  method: string
  headers: Record<string, string>
  query_params: Record<string, unknown>
  body: unknown
  captured_at: string
}

export async function getWebhookUrls(workflowId: string): Promise<WebhookUrls> {
  return authorizedRequest<WebhookUrls>(
    `/workflows/${workflowId}/webhook/urls`,
    { method: "GET" },
  )
}

export async function listenForTestEvent(
  workflowId: string,
  nodeId: string,
  timeoutSeconds = 120,
  options?: { fresh?: boolean; signal?: AbortSignal },
): Promise<WebhookCapture> {
  const qs = new URLSearchParams({
    node_id: nodeId,
    timeout_seconds: String(timeoutSeconds),
  })
  if (options?.fresh) qs.set("fresh", "true")
  return authorizedRequest<WebhookCapture>(
    `/workflows/${workflowId}/webhook/listen?${qs.toString()}`,
    { method: "POST", signal: options?.signal },
  )
}

export async function clearWebhookCaptures(
  workflowId: string,
  nodeId: string,
): Promise<void> {
  const qs = new URLSearchParams({ node_id: nodeId })
  await authorizedRequest<void>(
    `/workflows/${workflowId}/webhook/listen?${qs.toString()}`,
    { method: "DELETE" },
  )
}
