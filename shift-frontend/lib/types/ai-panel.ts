export type AgentMessageRole = "user" | "assistant" | "tool" | "system"

export interface ExecutedToolCall {
  step: number
  toolName: string
  success: boolean
  preview: string
  durationMs: number
  error?: string
  running?: boolean
}

export interface ProposedToolCall {
  toolName: string
  arguments: Record<string, unknown>
  rationale: string
  requiresApproval: boolean
}

export interface PlanStep {
  step: number
  description: string
  toolCalls: ProposedToolCall[]
}

export interface ProposedPlan {
  intent: string
  summary: string
  impact: string
  steps: PlanStep[]
}

export interface ClarificationOption {
  value: string
  label: string
  hint?: string
}

/**
 * Payload estruturado que acompanha uma pergunta do agente quando ele
 * precisa oferecer opcoes selecionaveis (chips/radio no chat) em vez de
 * texto livre. O backend emite via EVT_CLARIFICATION e persiste em
 * msg_metadata.clarification para rehidratacao ao reabrir a thread.
 */
export interface ClarificationPayload {
  kind: "choice" | "multi_choice"
  field: "connection_id" | "trigger_type" | "workflow_id" | "target_table" | "other"
  question: string
  options: ClarificationOption[]
  extraOption?: ClarificationOption
}

export interface AgentMessage {
  id: string
  role: AgentMessageRole
  content: string | null
  toolName?: string
  createdAt: string
  isStreaming?: boolean
  failed?: boolean
  thinkingNode?: string
  isGuardrailsRefusal?: boolean
  planProposed?: ProposedPlan
  approvalId?: string
  approvalStatus?: "pending" | "approved" | "rejected"
  approvalRejectedReason?: string
  toolCallsExecuted?: ExecutedToolCall[]
  // Pergunta curta de clarificacao (texto sempre presente). Se vier com
  // `clarification.options`, renderizamos como AIClarificationCard (chips
  // clicaveis) em vez de texto plano.
  clarificationQuestion?: string
  clarification?: ClarificationPayload
  clarificationStatus?: "pending" | "answered"
  // Resposta que o usuario escolheu via chip — usada para desabilitar o
  // card apos o clique enquanto o stream da nova resposta acontece.
  clarificationAnswer?: string
}

export interface AgentThreadSummary {
  id: string
  title: string | null
  status: "running" | "awaiting_approval" | "completed" | "rejected" | "expired" | "error"
  createdAt: string
  updatedAt: string
}

export interface AgentThreadDetail extends AgentThreadSummary {
  messages: AgentMessage[]
  pendingApproval: {
    id: string
    proposedPlan: ProposedPlan
    expiresAt: string
  } | null
}

// Raw SSE types (snake_case from backend)
interface RawToolCall {
  tool_name: string
  arguments: Record<string, unknown>
  rationale: string
  requires_approval: boolean
}

interface RawPlanStep {
  step: number
  description: string
  tool_calls: RawToolCall[]
}

export interface RawProposedPlan {
  intent?: string | { intent?: string; summary?: string } | null
  summary?: string | null
  impact?: string | null
  steps?: RawPlanStep[] | null
  actions?: Array<{
    tool?: string
    arguments?: Record<string, unknown>
    rationale?: string
    requires_approval?: boolean
  }> | null
}

export interface RawClarificationOption {
  value?: string | null
  label?: string | null
  hint?: string | null
}

export interface RawClarificationPayload {
  kind?: string | null
  field?: string | null
  question?: string | null
  options?: RawClarificationOption[] | null
  extra_option?: RawClarificationOption | null
}

export function convertRawClarification(
  raw: RawClarificationPayload | null | undefined,
  fallbackQuestion?: string,
): ClarificationPayload | undefined {
  if (!raw || typeof raw !== "object") return undefined
  const kind: ClarificationPayload["kind"] =
    raw.kind === "multi_choice" ? "multi_choice" : "choice"
  const field: ClarificationPayload["field"] = ((): ClarificationPayload["field"] => {
    switch (raw.field) {
      case "connection_id":
      case "trigger_type":
      case "workflow_id":
      case "target_table":
        return raw.field
      default:
        return "other"
    }
  })()
  const question = (raw.question ?? fallbackQuestion ?? "").trim()
  const options = Array.isArray(raw.options)
    ? raw.options
        .filter((o): o is NonNullable<typeof o> => Boolean(o))
        .map((o) => ({
          value: String(o.value ?? ""),
          label: String(o.label ?? o.value ?? "").trim() || "Opcao",
          hint: o.hint ? String(o.hint) : undefined,
        }))
        .filter((o) => o.value.length > 0)
    : []
  if (!question || options.length === 0) return undefined
  const extraRaw = raw.extra_option ?? undefined
  const extraOption =
    extraRaw && extraRaw.value && extraRaw.label
      ? {
          value: String(extraRaw.value),
          label: String(extraRaw.label),
          hint: extraRaw.hint ? String(extraRaw.hint) : undefined,
        }
      : undefined
  return { kind, field, question, options, extraOption }
}

export type AgentSSEEvent =
  | { type: "meta"; data: { model: string; resuming?: boolean } }
  | { type: "thinking"; data: { node: string } }
  | { type: "guardrails_refuse"; data: { reason: string } }
  | { type: "intent_detected"; data: { intent: string; description: string } }
  | { type: "plan_proposed"; data: { plan: RawProposedPlan } }
  | { type: "approval_required"; data: { approval_id: string; plan: RawProposedPlan } }
  | { type: "tool_call_start"; data: { step: number; tool_name: string; arguments: Record<string, unknown> } }
  | { type: "tool_call_end"; data: { step: number; tool_name: string; success: boolean; preview: string; duration_ms: number; error?: string } }
  | { type: "delta"; data: { text: string } }
  | { type: "done"; data: { thread_status: string } }
  | { type: "error"; data: { message: string } }
  | { type: "thread_created"; data: { thread_id: string } }
  | {
      type: "clarification_required"
      data: {
        question: string
        clarification: RawClarificationPayload | null
      }
    }

export function convertRawPlan(raw: RawProposedPlan | null | undefined): ProposedPlan {
  // Defensive: eventos do backend podem chegar com plan=null (ex.: approval
  // sem plano estruturado). Retorna um placeholder em vez de crashar.
  if (!raw || typeof raw !== "object") {
    return {
      intent: "acao",
      summary: "Plano de acao sugerido pelo agente.",
      impact: "",
      steps: [],
    }
  }

  const steps = Array.isArray(raw.steps)
    ? raw.steps
        .filter((s): s is NonNullable<typeof s> => Boolean(s))
        .map((s) => ({
          step: s.step,
          description: s.description,
          toolCalls: Array.isArray(s.tool_calls)
            ? s.tool_calls.map((t) => ({
                toolName: t.tool_name,
                arguments: t.arguments,
                rationale: t.rationale,
                requiresApproval: t.requires_approval,
              }))
            : [],
        }))
    : Array.isArray(raw.actions)
      ? raw.actions.map((action, index) => ({
          step: index + 1,
          description: action.rationale || `Executar ${action.tool ?? "acao"}`,
          toolCalls: [
            {
              toolName: action.tool ?? "acao",
              arguments: action.arguments ?? {},
              rationale: action.rationale ?? "",
              requiresApproval: Boolean(action.requires_approval),
            },
          ],
        }))
      : []

  const intent =
    typeof raw.intent === "string"
      ? raw.intent
      : raw.intent?.intent ?? "acao"

  const summary =
    raw.summary
    ?? (typeof raw.intent === "object" ? raw.intent?.summary : undefined)
    ?? "Plano de acao sugerido pelo agente."

  return {
    intent,
    summary,
    impact: raw.impact ?? "",
    steps,
  }
}
