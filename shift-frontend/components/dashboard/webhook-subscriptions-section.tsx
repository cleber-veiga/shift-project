"use client"

/**
 * Painel de webhooks de SAIDA — assinaturas que recebem POST do Shift quando
 * uma execucao do workspace muda de estado (completed/failed/cancelled).
 *
 * UI minimalista deliberada:
 * - Lista assinaturas do workspace selecionado.
 * - Cria/edita/desativa/apaga.
 * - Mostra ultimo status code + linha do tempo das ultimas entregas.
 * - Botoes de "testar" (POST sintetico imediato) e "replay" de dead-letter.
 *
 * Permissoes: workspace MANAGER. Sem MANAGER, mostra mensagem e nada mais.
 */

import { useCallback, useEffect, useMemo, useState } from "react"
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Copy,
  Loader2,
  Plus,
  RefreshCw,
  RotateCcw,
  Trash2,
  XCircle,
  Zap,
} from "lucide-react"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useToast } from "@/lib/context/toast-context"
import { hasWorkspacePermission } from "@/lib/permissions"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import {
  type CreateSubscriptionInput,
  type WebhookDeadLetter,
  type WebhookDelivery,
  type WebhookEvent,
  type WebhookSubscription,
  createSubscription,
  deleteSubscription,
  listDeadLetters,
  listDeliveries,
  listSubscriptions,
  replayDeadLetter,
  testSubscription,
  updateSubscription,
} from "@/lib/api/webhook-subscriptions"


const ALL_EVENTS: WebhookEvent[] = [
  "execution.completed",
  "execution.failed",
  "execution.cancelled",
]


function formatDate(iso: string | null | undefined) {
  if (!iso) return "—"
  try {
    return new Intl.DateTimeFormat("pt-BR", {
      day: "2-digit",
      month: "2-digit",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(iso))
  } catch {
    return iso
  }
}


function StatusBadge({ code }: { code: number | null }) {
  if (code === null) {
    return (
      <span className="inline-flex rounded bg-muted px-2 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
        Sem entregas
      </span>
    )
  }
  if (code >= 200 && code < 300) {
    return (
      <span className="inline-flex rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-emerald-600 dark:text-emerald-400">
        {code}
      </span>
    )
  }
  if (code >= 400 && code < 500) {
    return (
      <span className="inline-flex rounded bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-amber-600 dark:text-amber-400">
        {code}
      </span>
    )
  }
  return (
    <span className="inline-flex rounded bg-red-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-red-600 dark:text-red-400">
      {code}
    </span>
  )
}


function DeliveryStatusIcon({ status }: { status: WebhookDelivery["status"] }) {
  if (status === "delivered") {
    return <CheckCircle2 className="h-4 w-4 text-emerald-500" />
  }
  if (status === "failed") {
    return <XCircle className="h-4 w-4 text-red-500" />
  }
  if (status === "in_flight") {
    return <Loader2 className="h-4 w-4 animate-spin text-blue-500" />
  }
  return <Clock className="h-4 w-4 text-amber-500" />
}


// ---------------------------------------------------------------------------
// Componente principal
// ---------------------------------------------------------------------------


export function WebhookSubscriptionsSection() {
  const { selectedWorkspace } = useDashboard()
  const toast = useToast()
  const canManage = hasWorkspacePermission(
    selectedWorkspace?.my_role ?? null,
    "MANAGER",
  )

  const [subs, setSubs] = useState<WebhookSubscription[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<WebhookSubscription | null>(null)
  const [deleting, setDeleting] = useState(false)
  const [expandedId, setExpandedId] = useState<string | null>(null)
  const [revealedSecret, setRevealedSecret] = useState<{ id: string; secret: string } | null>(null)

  const workspaceId = selectedWorkspace?.id ?? null

  const load = useCallback(async () => {
    if (!workspaceId) return
    setLoading(true)
    try {
      const items = await listSubscriptions(workspaceId)
      setSubs(items)
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao listar.")
    } finally {
      setLoading(false)
    }
  }, [workspaceId, toast])

  useEffect(() => { load() }, [load])

  const handleCreate = async (payload: CreateSubscriptionInput) => {
    const created = await createSubscription(payload)
    setRevealedSecret({ id: created.id, secret: created.secret })
    toast.success(
      "Webhook criado",
      "Copie o secret agora — ele nao sera mostrado novamente.",
    )
    await load()
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteSubscription(deleteTarget.id)
      toast.success("Removido", deleteTarget.url)
      setDeleteTarget(null)
      await load()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao remover.")
    } finally {
      setDeleting(false)
    }
  }

  const handleToggleActive = async (sub: WebhookSubscription) => {
    try {
      await updateSubscription(sub.id, { active: !sub.active })
      await load()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao atualizar.")
    }
  }

  const handleTest = async (sub: WebhookSubscription) => {
    try {
      const r = await testSubscription(sub.id)
      if (r.success) {
        toast.success("Teste enviado", `${sub.url} respondeu ${r.status_code}`)
      } else {
        toast.error(
          "Teste falhou",
          `${r.status_code ?? "sem resposta"} ${r.error ? `— ${r.error}` : ""}`,
        )
      }
      await load()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha no teste.")
    }
  }

  if (!workspaceId) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border bg-card">
        <p className="text-sm text-muted-foreground">
          Selecione um workspace para gerenciar webhooks.
        </p>
      </div>
    )
  }

  if (!canManage) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border bg-card">
        <p className="text-sm text-muted-foreground">
          Apenas MANAGER do workspace pode gerenciar webhooks.
        </p>
      </div>
    )
  }

  return (
    <div className="space-y-4" data-testid="webhook-subscriptions-section">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold">Webhooks de saida</h2>
          <p className="text-sm text-muted-foreground">
            Receba POST do Shift quando execucoes deste workspace mudam de estado.
            Cada request inclui ``X-Shift-Signature`` (HMAC-SHA256).
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={load}
            className="inline-flex items-center gap-1 rounded-md border border-border bg-background px-3 py-1.5 text-sm hover:bg-muted"
          >
            <RefreshCw className="h-4 w-4" /> Recarregar
          </button>
          <button
            type="button"
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" /> Novo webhook
          </button>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" /> Carregando...
        </div>
      ) : subs.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-card p-8 text-center">
          <p className="text-sm text-muted-foreground">
            Nenhum webhook configurado. Crie um para receber notificacoes
            de execucoes terminadas.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {subs.map((sub) => (
            <SubscriptionRow
              key={sub.id}
              sub={sub}
              expanded={expandedId === sub.id}
              onToggle={() => setExpandedId(expandedId === sub.id ? null : sub.id)}
              onDelete={() => setDeleteTarget(sub)}
              onTest={() => handleTest(sub)}
              onToggleActive={() => handleToggleActive(sub)}
              onReplay={load}
            />
          ))}
        </ul>
      )}

      {showCreate && (
        <CreateModal
          workspaceId={workspaceId}
          onCreate={handleCreate}
          onClose={() => setShowCreate(false)}
        />
      )}

      {revealedSecret && (
        <SecretRevealedModal
          secret={revealedSecret.secret}
          onClose={() => setRevealedSecret(null)}
        />
      )}

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => { if (!open) setDeleteTarget(null) }}
        title="Remover webhook?"
        description={`Esta acao apaga a inscricao "${deleteTarget?.url ?? ""}" e seu historico de entregas. Nao pode ser desfeita.`}
        confirmText="Remover"
        confirmVariant="destructive"
        loading={deleting}
        onConfirm={handleDelete}
      />
    </div>
  )
}


// ---------------------------------------------------------------------------
// Linha de subscription (com expandable de deliveries / dead-letters)
// ---------------------------------------------------------------------------


function SubscriptionRow({
  sub,
  expanded,
  onToggle,
  onDelete,
  onTest,
  onToggleActive,
  onReplay,
}: {
  sub: WebhookSubscription
  expanded: boolean
  onToggle: () => void
  onDelete: () => void
  onTest: () => void
  onToggleActive: () => void
  onReplay: () => void
}) {
  return (
    <li className="rounded-lg border border-border bg-card">
      <div className="flex items-center gap-3 p-3">
        <button
          type="button"
          onClick={onToggle}
          className={`flex h-8 w-8 items-center justify-center rounded-md ${sub.active ? "bg-emerald-500/10 text-emerald-500" : "bg-muted text-muted-foreground"}`}
          title={sub.active ? "Ativo" : "Pausado"}
        >
          <Zap className="h-4 w-4" />
        </button>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <code className="truncate text-sm font-medium">{sub.url}</code>
            <StatusBadge code={sub.last_status_code} />
            {!sub.active && (
              <span className="inline-flex rounded bg-muted px-2 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
                Pausado
              </span>
            )}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            {sub.events.map((e) => (
              <span
                key={e}
                className="rounded bg-muted px-1.5 py-0.5 text-[10px] text-muted-foreground"
              >
                {e}
              </span>
            ))}
            <span className="text-xs text-muted-foreground">
              {sub.last_attempt_at
                ? `ultima tentativa em ${formatDate(sub.last_attempt_at)}`
                : "nenhuma entrega ainda"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-1">
          <IconBtn title="Testar" onClick={onTest}><Zap className="h-4 w-4" /></IconBtn>
          <IconBtn
            title={sub.active ? "Pausar" : "Reativar"}
            onClick={onToggleActive}
          >
            <RotateCcw className="h-4 w-4" />
          </IconBtn>
          <IconBtn title="Remover" onClick={onDelete} variant="destructive">
            <Trash2 className="h-4 w-4" />
          </IconBtn>
        </div>
      </div>

      {expanded && (
        <div className="border-t border-border p-3">
          <ExpandedDetails sub={sub} onReplay={onReplay} />
        </div>
      )}
    </li>
  )
}


function IconBtn({
  children,
  onClick,
  title,
  variant = "default",
}: {
  children: React.ReactNode
  onClick: () => void
  title: string
  variant?: "default" | "destructive"
}) {
  const cls =
    variant === "destructive"
      ? "text-red-500 hover:bg-red-500/10"
      : "text-muted-foreground hover:bg-muted hover:text-foreground"
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={title}
      className={`flex h-8 w-8 items-center justify-center rounded-md transition ${cls}`}
    >
      {children}
    </button>
  )
}


// ---------------------------------------------------------------------------
// Detalhes expandidos: ultimas entregas + dead-letters
// ---------------------------------------------------------------------------


function ExpandedDetails({
  sub,
  onReplay,
}: { sub: WebhookSubscription; onReplay: () => void }) {
  const toast = useToast()
  const [deliveries, setDeliveries] = useState<WebhookDelivery[]>([])
  const [deadLetters, setDeadLetters] = useState<WebhookDeadLetter[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    setLoading(true)
    try {
      const [d, dl] = await Promise.all([
        listDeliveries(sub.id, { limit: 10 }),
        listDeadLetters(sub.id, { limit: 10 }),
      ])
      setDeliveries(d)
      setDeadLetters(dl)
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao carregar.")
    } finally {
      setLoading(false)
    }
  }, [sub.id, toast])

  useEffect(() => { reload() }, [reload])

  const handleReplay = async (dl: WebhookDeadLetter) => {
    try {
      await replayDeadLetter(sub.id, dl.id)
      toast.success("Replay agendado", "Nova entrega criada na fila.")
      await reload()
      onReplay()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha no replay.")
    }
  }

  if (loading) {
    return (
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" /> Carregando entregas...
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase text-muted-foreground">
          Ultimas entregas
        </h4>
        {deliveries.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nenhuma entrega ainda.</p>
        ) : (
          <ul className="space-y-1">
            {deliveries.map((d) => (
              <li
                key={d.id}
                className="flex items-center gap-2 rounded border border-border/50 bg-background px-2 py-1.5 text-xs"
              >
                <DeliveryStatusIcon status={d.status} />
                <span className="font-medium">{d.event}</span>
                <span className="text-muted-foreground">
                  {d.attempt_count}/{d.max_attempts} tentativa{d.attempt_count !== 1 ? "s" : ""}
                </span>
                <span className="ml-auto text-muted-foreground">
                  {formatDate(d.created_at)}
                </span>
                {d.last_status_code !== null && (
                  <StatusBadge code={d.last_status_code} />
                )}
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <h4 className="mb-2 flex items-center gap-1 text-xs font-semibold uppercase text-muted-foreground">
          <AlertTriangle className="h-3 w-3" /> Dead-letters
        </h4>
        {deadLetters.length === 0 ? (
          <p className="text-sm text-muted-foreground">Nenhum dead-letter ativo.</p>
        ) : (
          <ul className="space-y-1">
            {deadLetters.map((dl) => (
              <li
                key={dl.id}
                className="flex items-center gap-2 rounded border border-red-500/30 bg-red-500/5 px-2 py-1.5 text-xs"
              >
                <span className="font-medium">{dl.event}</span>
                <span className="text-muted-foreground">{dl.attempt_count} tentativas</span>
                {dl.last_status_code !== null && (
                  <StatusBadge code={dl.last_status_code} />
                )}
                <span className="ml-auto text-muted-foreground">
                  {formatDate(dl.created_at)}
                </span>
                {dl.resolved_at === null && (
                  <button
                    type="button"
                    onClick={() => handleReplay(dl)}
                    className="rounded bg-primary px-2 py-0.5 text-[10px] font-medium text-primary-foreground hover:bg-primary/90"
                  >
                    Replay
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  )
}


// ---------------------------------------------------------------------------
// Modal de criacao (inline pra evitar mais um arquivo)
// ---------------------------------------------------------------------------


function CreateModal({
  workspaceId,
  onCreate,
  onClose,
}: {
  workspaceId: string
  onCreate: (payload: CreateSubscriptionInput) => Promise<void>
  onClose: () => void
}) {
  const [url, setUrl] = useState("")
  const [description, setDescription] = useState("")
  const [events, setEvents] = useState<WebhookEvent[]>(["execution.completed"])
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const toggleEvent = (e: WebhookEvent) => {
    setEvents((cur) =>
      cur.includes(e) ? cur.filter((x) => x !== e) : [...cur, e],
    )
  }

  const submit = async () => {
    if (!url || events.length === 0) {
      setError("URL e ao menos um evento sao obrigatorios.")
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      await onCreate({ workspace_id: workspaceId, url, events, description })
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : "Falha ao criar.")
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-5 shadow-lg">
        <h3 className="text-base font-semibold">Novo webhook</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          O Shift envia POST com payload JSON e header X-Shift-Signature
          (HMAC-SHA256). Recomendado validar a assinatura no servidor.
        </p>
        <div className="mt-4 space-y-3">
          <label className="block text-sm">
            URL HTTPS
            <input
              type="url"
              value={url}
              onChange={(e) => setUrl(e.target.value)}
              placeholder="https://meuapp.com/webhooks/shift"
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
          </label>
          <label className="block text-sm">
            Descricao (opcional)
            <input
              type="text"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="CRM principal"
              className="mt-1 w-full rounded-md border border-border bg-background px-3 py-2 text-sm"
            />
          </label>
          <div>
            <p className="text-sm">Eventos</p>
            <div className="mt-1 flex flex-wrap gap-2">
              {ALL_EVENTS.map((e) => {
                const on = events.includes(e)
                return (
                  <button
                    key={e}
                    type="button"
                    onClick={() => toggleEvent(e)}
                    className={`rounded-md border px-2 py-1 text-xs transition ${on ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"}`}
                  >
                    {e}
                  </button>
                )
              })}
            </div>
          </div>
          {error && <p className="text-xs text-red-500">{error}</p>}
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-muted disabled:opacity-50"
          >
            Cancelar
          </button>
          <button
            type="button"
            onClick={submit}
            disabled={submitting}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
          >
            {submitting && <Loader2 className="h-4 w-4 animate-spin" />}
            Criar
          </button>
        </div>
      </div>
    </div>
  )
}


function SecretRevealedModal({
  secret,
  onClose,
}: { secret: string; onClose: () => void }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(secret)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // fallback silencioso
    }
  }
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-lg rounded-lg border border-border bg-card p-5 shadow-lg">
        <h3 className="text-base font-semibold">Secret HMAC criado</h3>
        <p className="mt-1 text-sm text-muted-foreground">
          Copie agora — o Shift NUNCA mais vai exibir esse valor.
          Use-o no servidor para validar X-Shift-Signature.
        </p>
        <div className="mt-3 flex items-center gap-2 rounded-md border border-border bg-background p-2">
          <code className="flex-1 truncate text-xs">{secret}</code>
          <button
            type="button"
            onClick={copy}
            className="inline-flex items-center gap-1 rounded-md bg-primary px-2 py-1 text-xs font-medium text-primary-foreground hover:bg-primary/90"
          >
            <Copy className="h-3 w-3" /> {copied ? "Copiado!" : "Copiar"}
          </button>
        </div>
        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
          >
            Entendi
          </button>
        </div>
      </div>
    </div>
  )
}
