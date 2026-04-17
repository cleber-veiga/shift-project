"use client"

import { Grid2X2, List, Loader2, Plus, Search, Workflow, FolderOpen, Play, Trash2 } from "lucide-react"
import Link from "next/link"
import { useRouter } from "next/navigation"
import { useCallback, useEffect, useState } from "react"
import { useDashboard } from "@/lib/context/dashboard-context"
import {
  type DashboardScope,
  type DashboardSection,
  getDashboardSectionMeta,
} from "@/lib/dashboard-navigation"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { hasWorkspacePermission } from "@/lib/permissions"
import { AccessMatrixSection } from "@/components/dashboard/access-matrix-section"
import { ConnectionsSection } from "@/components/dashboard/connections-section"
import { CustomNodeDefinitionsSection } from "@/components/dashboard/custom-node-definitions-section"
import { DeadLettersSection } from "@/components/dashboard/dead-letters-section"
import { EconomicGroupSection } from "@/components/dashboard/economic-group-section"
import { InputModelsSection } from "@/components/dashboard/input-models-section"
import { MembersSection } from "@/components/dashboard/members-section"
import { NewWorkflowModal } from "@/components/workflow/new-workflow-modal"
import { listWorkspaceWorkflows, deleteWorkflow, listWorkspacePlayers, type Workflow as WorkflowType, type WorkspacePlayer } from "@/lib/auth"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"

interface ContextSectionPageProps {
  scope: DashboardScope
  section: DashboardSection
}

function FlowsSection({
  scope,
  scopeName,
}: {
  scope: DashboardScope
  scopeName: string
}) {
  const router = useRouter()
  const { selectedWorkspace } = useDashboard()
  const wsRole = selectedWorkspace?.my_role ?? null
  const canCreateFlow = hasWorkspacePermission(wsRole, "CONSULTANT")
  const canDeleteFlow = hasWorkspacePermission(wsRole, "MANAGER")
  const [view, setView] = useState<"list" | "card">("list")
  const [showNewModal, setShowNewModal] = useState(false)
  const [searchTerm, setSearchTerm] = useState("")
  const [statusFilter, setStatusFilter] = useState("todos")

  // Real data
  const [workflows, setWorkflows] = useState<WorkflowType[]>([])
  const [players, setPlayers] = useState<WorkspacePlayer[]>([])
  const [loading, setLoading] = useState(true)
  const [deleteTarget, setDeleteTarget] = useState<WorkflowType | null>(null)
  const [deleting, setDeleting] = useState(false)

  const loadWorkflows = useCallback(async () => {
    if (!selectedWorkspace?.id) return
    setLoading(true)
    try {
      const [data, playerData] = await Promise.all([
        listWorkspaceWorkflows(selectedWorkspace.id),
        listWorkspacePlayers(selectedWorkspace.id),
      ])
      setWorkflows(data)
      setPlayers(playerData)
    } catch {
      setWorkflows([])
    } finally {
      setLoading(false)
    }
  }, [selectedWorkspace?.id])

  useEffect(() => { loadWorkflows() }, [loadWorkflows])

  const handleDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteWorkflow(deleteTarget.id)
      setWorkflows((prev) => prev.filter((w) => w.id !== deleteTarget.id))
      setDeleteTarget(null)
    } catch {
      // keep dialog open
    } finally {
      setDeleting(false)
    }
  }

  function formatDate(iso: string) {
    try { return new Intl.DateTimeFormat("pt-BR", { day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(iso)) }
    catch { return iso }
  }

  function getStatus(w: WorkflowType) {
    return w.is_published ? "ATIVO" : "RASCUNHO"
  }

  function getPlayerName(flow: WorkflowType): string | null {
    const meta = flow.definition?.meta as Record<string, unknown> | undefined
    if ((meta?.workflow_type as string) !== "data-migration") return null
    const playerId = meta?.player_id as string | undefined
    if (!playerId) return "—"
    return players.find((p) => p.id === playerId)?.name ?? "—"
  }

  const filtered = workflows.filter((w) => {
    if (statusFilter === "rascunho" && w.is_published) return false
    if (statusFilter === "ativo" && !w.is_published) return false
    if (searchTerm && !w.name.toLowerCase().includes(searchTerm.toLowerCase())) return false
    return true
  })

  return (
    <>
    <NewWorkflowModal open={showNewModal} onOpenChange={(open) => {
      setShowNewModal(open)
      if (!open) loadWorkflows() // refresh list when modal closes after creation
    }} />
    <ConfirmDialog
      open={!!deleteTarget}
      onOpenChange={(open) => !open && setDeleteTarget(null)}
      title="Excluir Fluxo"
      description={`Tem certeza que deseja excluir "${deleteTarget?.name}"? Esta ação não pode ser desfeita.`}
      confirmText="Excluir"
      confirmVariant="destructive"
      loading={deleting}
      onConfirm={handleDelete}
    />
    <section className="space-y-3">
      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-flex w-fit items-center rounded-md border border-border bg-background p-1">
          <button
            type="button"
            onClick={() => setView("list")}
            className={`inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-xs font-medium transition-colors ${
              view === "list" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <List className="size-3.5" />
            Lista
          </button>
          <button
            type="button"
            onClick={() => setView("card")}
            className={`inline-flex h-7 items-center gap-1.5 rounded px-2.5 text-xs font-medium transition-colors ${
              view === "card" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Grid2X2 className="size-3.5" />
            Card
          </button>
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <Select defaultValue="todos" onValueChange={setStatusFilter}>
            <SelectTrigger className="w-full min-w-40 bg-background sm:w-[160px]">
              <SelectValue placeholder="Todos os Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="todos">Todos os Status</SelectItem>
              <SelectItem value="rascunho">Rascunho</SelectItem>
              <SelectItem value="ativo">Ativo</SelectItem>
            </SelectContent>
          </Select>

          <label className="flex h-9 w-full items-center gap-2 rounded-md border border-input bg-background px-3 sm:w-[220px]">
            <Search className="size-4 text-muted-foreground" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Buscar..."
              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>

          {canCreateFlow ? (
            <button
              type="button"
              onClick={() => setShowNewModal(true)}
              className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-foreground px-3.5 text-sm font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Plus className="size-4" />
              Novo Fluxo
            </button>
          ) : null}
        </div>
      </div>

      {loading ? (
        <div className="flex h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Carregando fluxos...
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border bg-card">
          <p className="text-sm text-muted-foreground">
            {workflows.length === 0 ? "Nenhum fluxo criado ainda" : "Nenhum resultado encontrado"}
          </p>
        </div>
      ) : view === "list" ? (
        <div className="overflow-auto rounded-xl border border-border bg-card shadow-sm">
          <div className="grid min-w-[860px] grid-cols-[1fr_180px_140px_120px_120px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Fluxo</span>
            <span className="text-left">Sistema</span>
            <span className="text-left">Status</span>
            <span className="text-left">Atualizado</span>
            <span className="text-right">Ações</span>
          </div>

          <div className="divide-y divide-border">
            {filtered.map((flow) => (
              <div
                key={flow.id}
                className="grid min-w-[860px] grid-cols-[1fr_180px_140px_120px_120px] items-center px-4 py-4 transition-colors hover:bg-muted/10"
              >
                <div className="flex items-center gap-3">
                  <div className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <Workflow className="size-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-foreground">{flow.name}</p>
                    <p className="text-[11px] text-muted-foreground">{flow.description || scopeName}</p>
                  </div>
                </div>

                <div>
                  {getPlayerName(flow) !== null ? (
                    <span className="inline-flex rounded bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                      {getPlayerName(flow)}
                    </span>
                  ) : (
                    <span className="text-[11px] text-muted-foreground">—</span>
                  )}
                </div>

                <div>
                  <span className={`inline-flex rounded px-2 py-0.5 text-[10px] font-medium uppercase ${
                    flow.is_published ? "bg-emerald-500/10 text-emerald-600" : "bg-muted text-muted-foreground"
                  }`}>
                    {getStatus(flow)}
                  </span>
                </div>

                <p className="text-[12px] text-foreground">{formatDate(flow.updated_at)}</p>

                <div className="flex items-center justify-end gap-1">
                  <button
                    type="button"
                    onClick={() => router.push(`/workflow/${flow.id}`)}
                    className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    aria-label="Abrir fluxo"
                  >
                    <FolderOpen className="size-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => router.push(`/workflow/${flow.id}`)}
                    className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                    aria-label="Executar fluxo"
                  >
                    <Play className="size-4" />
                  </button>
                  {canDeleteFlow ? (
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(flow)}
                      className="rounded p-2 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive"
                      aria-label="Excluir fluxo"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((flow) => (
            <article
              key={flow.id}
              className="rounded-xl border border-border bg-card p-4 shadow-sm transition-colors hover:bg-muted/10"
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex size-9 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <Workflow className="size-4" />
                  </div>
                  <div>
                    <h3 className="text-sm font-semibold text-foreground">{flow.name}</h3>
                    <p className="mt-1 text-xs text-muted-foreground">{flow.description || scopeName}</p>
                  </div>
                </div>
                <span className={`inline-flex rounded px-2 py-0.5 text-[10px] font-medium uppercase ${
                  flow.is_published ? "bg-emerald-500/10 text-emerald-600" : "bg-muted text-muted-foreground"
                }`}>
                  {getStatus(flow)}
                </span>
              </div>

              {getPlayerName(flow) !== null && (
                <div className="mt-3">
                  <span className="inline-flex rounded bg-primary/10 px-2 py-0.5 text-[11px] font-medium text-primary">
                    {getPlayerName(flow)}
                  </span>
                </div>
              )}

              <div className="mt-4 flex items-center justify-between text-xs text-muted-foreground">
                <span>{formatDate(flow.updated_at)}</span>
                <div className="flex items-center gap-1">
                  <button
                    type="button"
                    onClick={() => router.push(`/workflow/${flow.id}`)}
                    className="rounded p-2 transition-colors hover:bg-muted hover:text-foreground"
                    aria-label="Abrir fluxo"
                  >
                    <FolderOpen className="size-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => router.push(`/workflow/${flow.id}`)}
                    className="rounded p-2 transition-colors hover:bg-muted hover:text-foreground"
                    aria-label="Executar fluxo"
                  >
                    <Play className="size-4" />
                  </button>
                  {canDeleteFlow ? (
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(flow)}
                      className="rounded p-2 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive"
                      aria-label="Excluir fluxo"
                    >
                      <Trash2 className="size-4" />
                    </button>
                  ) : null}
                </div>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
    </>
  )
}

export function ContextSectionPage({ scope, section }: ContextSectionPageProps) {
  const { selectedOrganization, selectedWorkspace, selectedProject } = useDashboard()
  const meta = getDashboardSectionMeta(scope, section)
  const Icon = meta.icon
  const scopeLabel = scope === "space" ? "Espaço" : "Projeto"
  const scopeName =
    scope === "space" ? selectedWorkspace?.name ?? "Nenhum espaço selecionado" : selectedProject?.name ?? "Nenhum projeto selecionado"

  if (scope === "space" && meta.minWorkspaceRole && !hasWorkspacePermission(selectedWorkspace?.my_role, meta.minWorkspaceRole)) {
    return (
      <div className="flex h-64 flex-col items-center justify-center gap-3 rounded-2xl border border-dashed border-border bg-card/60 p-6 text-center">
        <div className="flex size-12 items-center justify-center rounded-full bg-destructive/10 text-destructive">
          <Icon className="size-5" />
        </div>
        <p className="text-base font-semibold text-foreground">Acesso restrito</p>
        <p className="max-w-md text-sm text-muted-foreground">
          Você não tem permissão para acessar esta seção. Fale com o gestor do workspace para solicitar acesso.
        </p>
        <Link
          href="/espaco/grupo-economico"
          className="mt-2 inline-flex h-9 items-center justify-center rounded-lg border border-border bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent"
        >
          Ir para Grupo Econômico
        </Link>
      </div>
    )
  }

  if (scope === "project" && !selectedProject) {
    return (
      <div className="space-y-6">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            <Icon className="size-3.5" />
            {scopeLabel}
          </div>
          <div>
            <h1 className="text-3xl font-semibold tracking-tight">{meta.label}</h1>
            <p className="mt-2 text-sm text-muted-foreground">{meta.description}</p>
          </div>
        </div>

        <div className="rounded-2xl border border-dashed border-border bg-card/60 p-6">
          <p className="text-base font-semibold text-foreground">Selecione um projeto para continuar</p>
          <p className="mt-2 text-sm text-muted-foreground">
            Esta área depende de um projeto ativo no seletor da sidebar. Depois de escolher um projeto, os mesmos módulos do espaço ficam disponíveis aqui no contexto do cliente.
          </p>
          <Link
            href="/home"
            className="mt-4 inline-flex h-10 items-center justify-center rounded-xl border border-border bg-background px-4 text-sm font-medium text-foreground transition hover:bg-accent"
          >
            Voltar para o espaço
          </Link>
        </div>
      </div>
    )
  }

  if (section === "grupo-economico") {
    return <EconomicGroupSection />
  }

  if (section === "fluxos") {
    return <FlowsSection scope={scope} scopeName={scopeName} />
  }

  if (section === "conexoes") {
    return <ConnectionsSection scope={scope} />
  }

  if (section === "nos-personalizados") {
    return <CustomNodeDefinitionsSection scope={scope} />
  }

  if (section === "modelos-entrada") {
    return <InputModelsSection />
  }

  if (section === "dead-letters") {
    return <DeadLettersSection />
  }

  if (section === "membros") {
    return <MembersSection scope={scope} />
  }

  if (section === "controle-acesso") {
    return <AccessMatrixSection />
  }

  return (
    <div className="space-y-6">
      <div className="space-y-3">
        <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
          <Icon className="size-3.5" />
          {scopeLabel}
        </div>
        <div>
          <h1 className="text-3xl font-semibold tracking-tight">{meta.label}</h1>
          <p className="mt-2 text-sm text-muted-foreground">{meta.description}</p>
        </div>
        <p className="text-sm text-muted-foreground">
          Organização: <span className="font-medium text-foreground">{selectedOrganization?.name ?? "-"}</span>
          {" "}|
          {" "}Workspace: <span className="font-medium text-foreground">{selectedWorkspace?.name ?? "-"}</span>
          {" "}|
          {" "}Projeto: <span className="font-medium text-foreground">{selectedProject?.name ?? "-"}</span>
        </p>
      </div>

      <section className="grid gap-4 xl:grid-cols-2">
        <article className="rounded-2xl border border-border bg-card p-5">
          <h2 className="text-base font-semibold">Escopo atual</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            {scope === "space"
              ? "Este grupo concentra recursos compartilhados do workspace atual."
              : "Este grupo concentra recursos exclusivos do projeto selecionado."}
          </p>
          <div className="mt-4 rounded-xl border border-border bg-background/70 p-4">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
              {scopeLabel}
            </p>
            <p className="mt-1 text-sm font-medium text-foreground">{scopeName}</p>
          </div>
        </article>

        <article className="rounded-2xl border border-border bg-card p-5">
          <h2 className="text-base font-semibold">Estrutura pronta</h2>
          <p className="mt-2 text-sm text-muted-foreground">
            A navegação lateral já está organizada com os mesmos módulos em `ESPAÇO` e `PROJETO`, permitindo evoluir cada tela dentro do escopo correto sem mudar a estrutura do layout.
          </p>
        </article>
      </section>
    </div>
  )
}
