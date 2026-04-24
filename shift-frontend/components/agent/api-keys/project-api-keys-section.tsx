"use client"

import { useState } from "react"
import { KeyRound, Plus, Search } from "lucide-react"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useToast } from "@/lib/context/toast-context"
import { hasWorkspacePermission } from "@/lib/permissions"
import { useApiKeys } from "@/lib/hooks/use-api-keys"
import type { AgentApiKey } from "@/lib/auth"
import type { CreateApiKeyInput, ProjectApiKeyCreated } from "@/lib/types/agent-api-key"
import { ApiKeysList } from "@/components/agent/api-keys/api-keys-list"
import { CreateApiKeyModal } from "@/components/agent/api-keys/create-api-key-modal"
import { ApiKeyCreatedDialog } from "@/components/agent/api-keys/api-key-created-dialog"
import { RevokeApiKeyDialog } from "@/components/agent/api-keys/revoke-api-key-dialog"

export function ProjectApiKeysSection() {
  const { selectedWorkspace, selectedProject } = useDashboard()
  const toast = useToast()
  const wsRole = selectedWorkspace?.my_role ?? null
  const canManage = hasWorkspacePermission(wsRole, "MANAGER")

  const { keys, isLoading, error, createKey, revokeKey } = useApiKeys()

  const [searchTerm, setSearchTerm] = useState("")
  const [showCreate, setShowCreate] = useState(false)
  const [createdKey, setCreatedKey] = useState<ProjectApiKeyCreated | null>(null)
  const [revokeTarget, setRevokeTarget] = useState<AgentApiKey | null>(null)
  const [revoking, setRevoking] = useState(false)

  const handleCreate = async (input: CreateApiKeyInput) => {
    const result = await createKey(input)
    setShowCreate(false)
    setCreatedKey(result)
    toast.success("Chave criada", "Copie o valor agora — não será exibido novamente.")
  }

  const handleRevoke = async () => {
    if (!revokeTarget) return
    setRevoking(true)
    try {
      await revokeKey(revokeTarget.id)
      toast.success("Chave revogada", `"${revokeTarget.name}" foi revogada com sucesso.`)
      setRevokeTarget(null)
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao revogar chave.")
    } finally {
      setRevoking(false)
    }
  }

  const filtered = keys.filter(
    (k) =>
      !searchTerm ||
      k.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      k.prefix.toLowerCase().includes(searchTerm.toLowerCase()),
  )

  const activeCount = keys.filter((k) => !k.revoked_at).length
  const projectName = selectedProject?.name ?? "este projeto"

  if (!canManage) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border bg-card/60 p-6 text-center">
        <div className="flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <KeyRound className="size-5" />
        </div>
        <p className="text-base font-semibold text-foreground">Acesso restrito</p>
        <p className="max-w-md text-sm text-muted-foreground">
          Apenas gerentes do workspace podem gerenciar chaves de API. Fale com o administrador do workspace para solicitar acesso.
        </p>
      </div>
    )
  }

  return (
    <>
      <CreateApiKeyModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        onCreate={handleCreate}
      />

      <ApiKeyCreatedDialog
        open={!!createdKey}
        plaintextKey={createdKey?.plaintextKey ?? ""}
        keyName={createdKey?.name ?? ""}
        onClose={() => setCreatedKey(null)}
      />

      <RevokeApiKeyDialog
        keyName={revokeTarget?.name ?? null}
        open={!!revokeTarget}
        loading={revoking}
        onOpenChange={(open) => !open && setRevokeTarget(null)}
        onConfirm={handleRevoke}
      />

      <section className="space-y-4">
        <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2">
            <KeyRound className="size-4 text-muted-foreground" />
            <span className="text-sm font-medium text-foreground">
              {activeCount} {activeCount === 1 ? "chave ativa" : "chaves ativas"}
              {" "}em <span className="font-semibold">{projectName}</span>
            </span>
            {keys.length - activeCount > 0 ? (
              <span className="text-xs text-muted-foreground">
                · {keys.length - activeCount} revogada{keys.length - activeCount > 1 ? "s" : ""}
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

            <button
              type="button"
              onClick={() => setShowCreate(true)}
              className="inline-flex h-8 items-center justify-center gap-1 rounded-md bg-foreground px-3 text-xs font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Plus className="size-3.5" />
              Nova Chave
            </button>
          </div>
        </div>

        <ApiKeysList
          keys={filtered}
          isLoading={isLoading}
          error={error}
          canManage={canManage}
          onRevoke={setRevokeTarget}
        />
      </section>
    </>
  )
}
