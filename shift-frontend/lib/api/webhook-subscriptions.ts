// Cliente HTTP para webhooks DE SAIDA — notificacao de clientes quando
// uma execucao do workspace termina. Diferente de ``lib/api/webhooks.ts``
// (esse cobre webhooks DE ENTRADA, do no Webhook do editor de workflows).

import { authorizedRequest } from "@/lib/auth"

export type WebhookEvent =
  | "execution.completed"
  | "execution.failed"
  | "execution.cancelled"

export interface WebhookSubscription {
  id: string
  workspace_id: string
  url: string
  events: WebhookEvent[]
  description: string | null
  active: boolean
  created_at: string
  updated_at: string
  last_attempt_at: string | null
  last_status_code: number | null
}

export interface WebhookSubscriptionCreated extends WebhookSubscription {
  // Apenas o POST inicial devolve. Cliente DEVE armazenar.
  secret: string
}

export interface WebhookSubscriptionRotated {
  id: string
  secret: string
}

export interface WebhookDelivery {
  id: string
  subscription_id: string
  event: string
  status: "pending" | "in_flight" | "delivered" | "failed"
  attempt_count: number
  max_attempts: number
  next_attempt_at: string
  last_status_code: number | null
  last_error: string | null
  delivered_at: string | null
  failed_at: string | null
  created_at: string
  execution_id: string | null
}

export interface WebhookDeliveryDetail extends WebhookDelivery {
  payload: Record<string, unknown>
}

export interface WebhookDeadLetter {
  id: string
  subscription_id: string
  delivery_id: string | null
  event: string
  last_status_code: number | null
  last_error: string | null
  attempt_count: number
  created_at: string
  resolved_at: string | null
}

export interface WebhookTestResponse {
  delivery_id: string | null
  status_code: number | null
  success: boolean
  error: string | null
}

export interface WebhookReplayResponse {
  new_delivery_id: string
  dead_letter_id: string
}

export interface CreateSubscriptionInput {
  workspace_id: string
  url: string
  events: WebhookEvent[]
  description?: string | null
  active?: boolean
}

export interface UpdateSubscriptionInput {
  url?: string
  events?: WebhookEvent[]
  description?: string | null
  active?: boolean
  rotate_secret?: boolean
}

const BASE = "/webhook-subscriptions"

export async function listSubscriptions(
  workspaceId: string,
): Promise<WebhookSubscription[]> {
  const qs = new URLSearchParams({ workspace_id: workspaceId })
  return authorizedRequest<WebhookSubscription[]>(
    `${BASE}?${qs.toString()}`,
    { method: "GET" },
  )
}

export async function getSubscription(
  id: string,
): Promise<WebhookSubscription> {
  return authorizedRequest<WebhookSubscription>(`${BASE}/${id}`, { method: "GET" })
}

export async function createSubscription(
  input: CreateSubscriptionInput,
): Promise<WebhookSubscriptionCreated> {
  return authorizedRequest<WebhookSubscriptionCreated>(BASE, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
}

export async function updateSubscription(
  id: string,
  input: UpdateSubscriptionInput,
): Promise<WebhookSubscription> {
  return authorizedRequest<WebhookSubscription>(`${BASE}/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  })
}

export async function rotateSecret(
  id: string,
): Promise<WebhookSubscriptionRotated> {
  return authorizedRequest<WebhookSubscriptionRotated>(
    `${BASE}/${id}/rotate-secret`,
    { method: "POST" },
  )
}

export async function deleteSubscription(id: string): Promise<void> {
  await authorizedRequest<void>(`${BASE}/${id}`, { method: "DELETE" })
}

export async function testSubscription(
  id: string,
  customPayload?: Record<string, unknown>,
): Promise<WebhookTestResponse> {
  return authorizedRequest<WebhookTestResponse>(`${BASE}/${id}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(
      customPayload ? { custom_payload: customPayload } : {},
    ),
  })
}

export async function listDeliveries(
  subscriptionId: string,
  options?: { limit?: number; status?: WebhookDelivery["status"] },
): Promise<WebhookDelivery[]> {
  const qs = new URLSearchParams()
  if (options?.limit) qs.set("limit", String(options.limit))
  if (options?.status) qs.set("status", options.status)
  const tail = qs.toString() ? `?${qs.toString()}` : ""
  return authorizedRequest<WebhookDelivery[]>(
    `${BASE}/${subscriptionId}/deliveries${tail}`,
    { method: "GET" },
  )
}

export async function getDelivery(
  subscriptionId: string,
  deliveryId: string,
): Promise<WebhookDeliveryDetail> {
  return authorizedRequest<WebhookDeliveryDetail>(
    `${BASE}/${subscriptionId}/deliveries/${deliveryId}`,
    { method: "GET" },
  )
}

export async function listDeadLetters(
  subscriptionId: string,
  options?: { includeResolved?: boolean; limit?: number },
): Promise<WebhookDeadLetter[]> {
  const qs = new URLSearchParams()
  if (options?.includeResolved) qs.set("include_resolved", "true")
  if (options?.limit) qs.set("limit", String(options.limit))
  const tail = qs.toString() ? `?${qs.toString()}` : ""
  return authorizedRequest<WebhookDeadLetter[]>(
    `${BASE}/${subscriptionId}/dead-letters${tail}`,
    { method: "GET" },
  )
}

export async function replayDeadLetter(
  subscriptionId: string,
  deadLetterId: string,
): Promise<WebhookReplayResponse> {
  return authorizedRequest<WebhookReplayResponse>(
    `${BASE}/${subscriptionId}/dead-letters/${deadLetterId}/replay`,
    { method: "POST" },
  )
}
