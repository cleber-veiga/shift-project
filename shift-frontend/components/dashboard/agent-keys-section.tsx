"use client"

import { useCallback, useEffect, useState } from "react"
import {
  BanIcon,
  KeyRound,
  Plus,
  Search,
  ShieldCheck,
  Trash2,
} from "lucide-react"
import { MorphLoader } from "@/components/ui/morph-loader"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useToast } from "@/lib/context/toast-context"
import { hasWorkspacePermission } from "@/lib/permissions"
import {
  type AgentApiKey,
  type AgentApiKeyCreatePayload,
  createAgentApiKey,
  deleteAgentApiKey,
  listAgentApiKeys,
  revokeAgentApiKey,
} from "@/lib/auth"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { CreateAgentKeyModal } from "@/components/dashboard/create-agent-key-modal"

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

function StatusBadge({ keyRow }: { keyRow: AgentApiKey }) {
  if (keyRow.revoked_at) {
    return (
      <span className="inline-flex rounded bg-muted px-2 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
        Revogada
      </span>
    )
  }
  if (keyRow.expires_at && new Date(keyRow.expires_at) < new Date()) {
    return (
      <span className="inline-flex rounded bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-amber-600 dark:text-amber-400">
        Expirada
      </span>
    )
  }
  return (
    <span className="inline-flex rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-emerald-600 dark:text-emerald-400">
      Ativa
    </span>
  )
}

export function AgentKeysSection() {
  const { selectedWorkspace } = useDashboard()
  const toast = useToast()
  const wsRole = selectedWorkspace?.my_role ?? null
  const canManage = hasWorkspacePermission(wsRole, "MANAGER")

  const [keys, setKeys] = useState<AgentApiKey[]>([])
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [showCreate, setShowCreate] = useState(false)
  const [revokeTarget, setRevokeTarget] = useState<AgentApiKey | null>(null)
  const [revoking, setRevoking] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState<AgentApiKey | null>(null)
  const [deleting, setDeleting] = useState(false)

  const workspaceId = selectedWorkspace?.id ?? null

  const loadKeys = useCallback(async () => {
    if (!workspaceId) return
    setLoading(true)
    try {
      const { items } = await listAgentApiKeys(workspaceId)
      setKeys(items)
    } catch (err) {
      toast.error(
        "Erro",
        err instanceof Error ? err.message : "Falha ao carregar chaves.",
      )
    } finally {
      setLoading(false)
    }
  }, [workspaceId, toast])

  useEffect(() => {
    loadKeys()
  }, [loadKeys])

  const handleCreate = async (payload: AgentApiKeyCreatePayload) => {
    const result = await createAgentApiKey(payload)
    toast.success("Chave criada", "Copie o plaintext agora — não será mostrado novamente.")
    await loadKeys()
    return { api_key: result.api_key }
  }

  const handleRevoke = async () => {
    if (!revokeTarget) return
    setRevoking(true)
    try {
      await revokeAgentApiKey(revokeTarget.id)
      toast.success("Chave revogada", `"${revokeTarget.name}" não poderá mais autenticar.`)
      setRevokeTarget(null)
      await loadKeys()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao revogar.")
    } finally {
      setRevoking(false)
    }
  }

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteAgentApiKey(deleteTarget.id)
      toast.success("Chave removida", `"${deleteTarget.name}" foi excluída.`)
      setDeleteTarget(null)
      await loadKeys()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao remover.")
    } finally {
      setDeleting(false)
    }
  }

  if (!workspaceId) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border bg-card">
        <p className="text-sm text-muted-foreground">
          Selecione um workspace para gerenciar chaves de API.
        </p>
      </div>
    )
  }

  const filtered = keys.filter(
    (k) =>
      !searchTerm ||
      k.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      k.prefix.toLowerCase().includes(searchTerm.toLowerCase()),
  )

  const activeCount = keys.filter((k) => !k.revoked_at).length

  return (
    <>
      <CreateAgentKeyModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        workspaceId={workspaceId}
        projectId={null}
        onCreate={handleCreate}
      />

      <ConfirmDialog
        open={!!revokeTarget}
        onOpenChange={(open) => !open && setRevokeTarget(null)}
        title="Revogar chave"
        description={`"${revokeTarget?.name}" será revogada imediatamente. Clientes MCP receberão 401. Tem certeza?`}
        confirmText="Revogar"
        confirmVariant="destructive"
        loading={revoking}
        onConfirm={handleRevoke}
      />

      <ConfirmDialog
        open={!!deleteTarget}
        onOpenChange={(open) => !open && setDeleteTarget(null)}
        title="Remover permanentemente"
        description={`"${deleteTarget?.name}" será apagada do banco. Esta ação não pode ser desfeita. Prefira revogar se quiser manter histórico de auditoria.`}
        confirmText="Remover"
        confirmVariant="destructive"
        loading={deleting}
        onConfirm={handleDelete}
      />

      <section className="space-y-4">
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <KeyRound className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium text-foreground">
              {activeCount} {activeCount === 1 ? "chave ativa" : "chaves ativas"}
            </span>
            {keys.length - activeCount > 0 ? (
              <span className="text-xs text-muted-foreground">
                + {keys.length - activeCount} revogada{keys.length - activeCount > 1 ? "s" : ""}
              </span>
            ) : null}
          </div>

          <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center">
            <label className="flex h-8 w-full items-center gap-1.5 rounded-md border border-input bg-background px-2.5 sm:w-[180px]">
              <Search className="size-3 text-muted-foreground" />
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                placeholder="Buscar por nome ou prefixo..."
                className="w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
              />
            </label>
            {canManage ? (
              <button
                type="button"
                onClick={() => setShowCreate(true)}
                className="inline-flex h-8 items-center justify-center gap-1 rounded-md bg-foreground px-3 text-xs font-semibold text-background transition-opacity hover:opacity-90"
              >
                <Plus className="size-3.5" />
                Nova Chave
              </button>
            ) : null}
          </div>
        </div>

        {loading ? (
          <div className="flex h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
            <MorphLoader className="size-4" /> Carregando chaves...
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border bg-card">
            <p className="text-sm text-muted-foreground">
              {keys.length === 0
                ? "Nenhuma chave criada ainda. Crie uma para conectar um cliente MCP."
                : "Nenhuma chave encontrada."}
            </p>
          </div>
        ) : (
          <div className="overflow-auto rounded-xl border border-border bg-card shadow-sm">
            <div className="grid min-w-[900px] grid-cols-[1fr_120px_100px_140px_140px_140px_120px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
              <span>Chave</span>
              <span>Papel máx.</span>
              <span>Aprovação</span>
              <span>Último uso</span>
              <span>Expira</span>
              <span>Status</span>
              <span className="text-right">Ações</span>
            </div>

            <div className="divide-y divide-border">
              {filtered.map((k) => (
                <div
                  key={k.id}
                  className="grid min-w-[900px] grid-cols-[1fr_120px_100px_140px_140px_140px_120px] items-center px-4 py-4 transition-colors hover:bg-muted/10"
                >
                  <div className="flex min-w-0 items-center gap-3">
                    <div className="flex size-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <KeyRound className="size-4" />
                    </div>
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-semibold text-foreground">
                        {k.name}
                      </p>
                      <p className="truncate font-mono text-[11px] text-muted-foreground">
                        {k.prefix}…
                      </p>
                      <p className="truncate text-[10px] text-muted-foreground">
                        {k.allowed_tools.includes("*")
                          ? "todas as tools"
                          : `${k.allowed_tools.length} tool${k.allowed_tools.length !== 1 ? "s" : ""}`}
                        {" · "}
                        {k.usage_count} uso{k.usage_count !== 1 ? "s" : ""}
                      </p>
                    </div>
                  </div>

                  <div>
                    <span className="inline-flex rounded bg-muted px-2 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
                      {k.max_workspace_role}
                    </span>
                  </div>

                  <div>
                    {k.require_human_approval ? (
                      <span className="inline-flex items-center gap-1 rounded bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-blue-600 dark:text-blue-400">
                        <ShieldCheck className="size-3" />
                        Sim
                      </span>
                    ) : (
                      <span className="inline-flex rounded bg-muted px-2 py-0.5 text-[10px] font-medium uppercase text-muted-foreground">
                        Não
                      </span>
                    )}
                  </div>

                  <p className="text-[12px] text-foreground">{formatDate(k.last_used_at)}</p>
                  <p className="text-[12px] text-foreground">{formatDate(k.expires_at)}</p>

                  <div>
                    <StatusBadge keyRow={k} />
                  </div>

                  <div className="flex items-center justify-end gap-1">
                    {canManage && !k.revoked_at ? (
                      <button
                        type="button"
                        onClick={() => setRevokeTarget(k)}
                        className="rounded p-2 text-amber-600/80 transition-colors hover:bg-muted hover:text-amber-600"
                        aria-label="Revogar chave"
                        title="Revogar (mantém histórico)"
                      >
                        <BanIcon className="size-4" />
                      </button>
                    ) : null}
                    {canManage ? (
                      <button
                        type="button"
                        onClick={() => setDeleteTarget(k)}
                        className="rounded p-2 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive"
                        aria-label="Remover chave"
                        title="Remover (hard delete)"
                      >
                        <Trash2 className="size-4" />
                      </button>
                    ) : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </section>
    </>
  )
}
