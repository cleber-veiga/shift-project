"use client"

import { Grid2X2, List, Loader2, Plus, Search, Workflow, FolderOpen, Play, Trash2, Copy, LayoutTemplate, Tag as TagIcon, Check, X } from "lucide-react"
import Link from "next/link"
import { useRouter, usePathname } from "next/navigation"
import { useCallback, useEffect, useMemo, useState } from "react"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useRegisterAIContext } from "@/lib/context/ai-context"
import type { AIContext } from "@/lib/types/ai-context"
import {
  type DashboardScope,
  type DashboardSection,
  getDashboardSectionMeta,
} from "@/lib/dashboard-navigation"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { hasWorkspacePermission } from "@/lib/permissions"
import { AccessMatrixSection } from "@/components/dashboard/access-matrix-section"
import { AgentActivitySection } from "@/components/agent/audit/agent-activity-section"
import { AgentKeysSection } from "@/components/dashboard/agent-keys-section"
import { ProjectApiKeysSection } from "@/components/agent/api-keys/project-api-keys-section"
import { ConnectionsSection } from "@/components/dashboard/connections-section"
import { CustomNodeDefinitionsSection } from "@/components/dashboard/custom-node-definitions-section"
import { DeadLettersSection } from "@/components/dashboard/dead-letters-section"
import { EconomicGroupSection } from "@/components/dashboard/economic-group-section"
import { InputModelsSection } from "@/components/dashboard/input-models-section"
import { MembersSection } from "@/components/dashboard/members-section"
import { NewWorkflowModal } from "@/components/workflow/new-workflow-modal"
import { CloneTemplateModal } from "@/components/workflow/clone-template-modal"
import { listWorkspaceWorkflows, listWorkspaceTemplates, deleteWorkflow, listWorkspacePlayers, type Workflow as WorkflowType, type WorkspacePlayer } from "@/lib/auth"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"

interface ContextSectionPageProps {
  scope: DashboardScope
  section: DashboardSection
}

function TemplatesSection({ workspaceId }: { workspaceId: string }) {
  const [templates, setTemplates] = useState<WorkflowType[]>([])
  const [loading, setLoading] = useState(true)
  const [cloneTarget, setCloneTarget] = useState<WorkflowType | null>(null)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listWorkspaceTemplates(workspaceId, { size: 200 })
      .then((data) => { if (!cancelled) setTemplates(data.items) })
      .catch(() => { if (!cancelled) setTemplates([]) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [workspaceId])

  if (loading) {
    return (
      <div className="flex h-20 items-center justify-center gap-2 text-xs text-muted-foreground">
        <Loader2 className="size-3.5 animate-spin" /> Carregando templates…
      </div>
    )
  }

  if (templates.length === 0) return null

  return (
    <>
      {cloneTarget && (
        <CloneTemplateModal
          template={cloneTarget}
          workspaceId={workspaceId}
          onClose={() => setCloneTarget(null)}
          onCloned={() => setCloneTarget(null)}
        />
      )}
      <section className="space-y-2 pt-2">
        <div className="flex items-center gap-2">
          <LayoutTemplate className="size-3.5 text-muted-foreground" />
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            Templates disponíveis
          </h2>
        </div>
        <div className="overflow-auto rounded-xl border border-border bg-card shadow-sm">
          <div className="grid min-w-[600px] grid-cols-[1fr_160px_120px] items-center border-b border-border px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Template</span>
            <span>Status</span>
            <span className="text-right">Ações</span>
          </div>
          <div className="divide-y divide-border">
            {templates.map((t) => (
              <div
                key={t.id}
                className="grid min-w-[600px] grid-cols-[1fr_160px_120px] items-center px-4 py-3 transition-colors hover:bg-muted/10"
              >
                <div className="flex items-center gap-3">
                  <div className="flex size-7 items-center justify-center rounded-md bg-violet-500/10 text-violet-600">
                    <LayoutTemplate className="size-3.5" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-foreground">{t.name}</p>
                    {t.description && (
                      <p className="truncate text-[11px] text-muted-foreground">{t.description}</p>
                    )}
                  </div>
                </div>
                <span className="inline-flex w-fit rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-emerald-600">
                  Publicado
                </span>
                <div className="flex justify-end">
                  <button
                    type="button"
                    onClick={() => setCloneTarget(t)}
                    className="flex items-center gap-1 rounded border border-border bg-card px-2.5 py-1 text-[11px] font-medium text-foreground transition hover:bg-muted"
                  >
                    <Copy className="size-3" />
                    Clonar
                  </button>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>
    </>
  )
}

function FlowsSection({
  scope,
  scopeName,
}: {
  scope: DashboardScope
  scopeName: string
}) {
  const router = useRouter()
  const { selectedWorkspace, selectedProject } = useDashboard()
  const wsRole = selectedWorkspace?.my_role ?? null
  const canCreateFlow = hasWorkspacePermission(wsRole, "CONSULTANT")
  const canDeleteFlow = hasWorkspacePermission(wsRole, "MANAGER")
  const [view, setView] = useState<"list" | "card">("list")
  const [showNewModal, setShowNewModal] = useState(false)
  const [searchTerm, setSearchTerm] = useState("")
  const [statusFilter, setStatusFilter] = useState("todos")
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [tagMenuOpen, setTagMenuOpen] = useState(false)

  // Real data
  const [workflows, setWorkflows] = useState<WorkflowType[]>([])
  const [players, setPlayers] = useState<WorkspacePlayer[]>([])
  const [loading, setLoading] = useState(true)

  const aiContext = useMemo<AIContext | null>(() => {
    if (loading) return null
    return {
      section: "workflows_list",
      scope: scope === "space" ? "workspace" : "project",
      workspaceId: selectedWorkspace?.id ?? null,
      workspaceName: selectedWorkspace?.name ?? null,
      projectId: selectedProject?.id ?? null,
      projectName: selectedProject?.name ?? null,
      userRole: {
        workspace: (wsRole ?? null) as "VIEWER" | "CONSULTANT" | "MANAGER" | null,
        project: null,
      },
      workflows: workflows.map((w) => ({
        id: w.id,
        name: w.name,
        status: w.is_published ? ("active" as const) : ("draft" as const),
        lastExecution: { status: null, at: null },
      })),
    }
  }, [loading, workflows, scope, selectedWorkspace, selectedProject, wsRole])

  useRegisterAIContext(aiContext)
  const [deleteTarget, setDeleteTarget] = useState<WorkflowType | null>(null)
  const [deleting, setDeleting] = useState(false)

  const loadWorkflows = useCallback(async () => {
    if (!selectedWorkspace?.id) return
    setLoading(true)
    try {
      const [data, playerData] = await Promise.all([
        listWorkspaceWorkflows(selectedWorkspace.id, { size: 200 }),
        listWorkspacePlayers(selectedWorkspace.id),
      ])
      setWorkflows(data.items)
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

  const availableTags = useMemo(() => {
    const set = new Set<string>()
    for (const w of workflows) for (const t of w.tags ?? []) set.add(t)
    return Array.from(set).sort()
  }, [workflows])

  const filtered = workflows.filter((w) => {
    if (statusFilter === "rascunho" && w.is_published) return false
    if (statusFilter === "ativo" && !w.is_published) return false
    if (searchTerm && !w.name.toLowerCase().includes(searchTerm.toLowerCase())) return false
    if (selectedTags.length > 0) {
      const wTags = new Set(w.tags ?? [])
      if (!selectedTags.some((t) => wTags.has(t))) return false
    }
    return true
  })

  function toggleTag(t: string) {
    setSelectedTags((prev) =>
      prev.includes(t) ? prev.filter((x) => x !== t) : [...prev, t]
    )
  }

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
      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="inline-flex w-fit items-center rounded border border-border bg-background p-0.5">
          <button
            type="button"
            onClick={() => setView("list")}
            className={`inline-flex h-6 items-center gap-1 rounded px-2 text-[11px] font-medium transition-colors ${
              view === "list" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <List className="size-3" />
            Lista
          </button>
          <button
            type="button"
            onClick={() => setView("card")}
            className={`inline-flex h-6 items-center gap-1 rounded px-2 text-[11px] font-medium transition-colors ${
              view === "card" ? "bg-accent text-foreground" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            <Grid2X2 className="size-3" />
            Card
          </button>
        </div>

        <div className="flex flex-col gap-1.5 sm:flex-row sm:items-center">
          <Select defaultValue="todos" onValueChange={setStatusFilter}>
            <SelectTrigger size="sm" className="w-full min-w-36 bg-background text-xs sm:w-[140px]">
              <SelectValue placeholder="Todos os Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="todos">Todos os Status</SelectItem>
              <SelectItem value="rascunho">Rascunho</SelectItem>
              <SelectItem value="ativo">Ativo</SelectItem>
            </SelectContent>
          </Select>

          <div className="relative">
            <button
              type="button"
              onClick={() => setTagMenuOpen((v) => !v)}
              className="flex h-8 w-full items-center gap-1.5 rounded-md border border-input bg-background px-2.5 text-xs text-foreground transition-colors hover:bg-muted sm:w-[150px]"
            >
              <TagIcon className="size-3 text-muted-foreground" />
              <span className="flex-1 text-left truncate">
                {selectedTags.length === 0
                  ? "Filtrar por tag"
                  : `${selectedTags.length} tag${selectedTags.length > 1 ? "s" : ""}`}
              </span>
              {selectedTags.length > 0 && (
                <span
                  role="button"
                  tabIndex={0}
                  onClick={(e) => {
                    e.stopPropagation()
                    setSelectedTags([])
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault()
                      e.stopPropagation()
                      setSelectedTags([])
                    }
                  }}
                  className="flex size-3.5 items-center justify-center rounded hover:bg-muted"
                  aria-label="Limpar tags"
                >
                  <X className="size-2.5" />
                </span>
              )}
            </button>
            {tagMenuOpen && (
              <>
                <div
                  className="fixed inset-0 z-40"
                  onClick={() => setTagMenuOpen(false)}
                />
                <div className="absolute right-0 z-50 mt-1 max-h-64 w-52 overflow-auto rounded-md border border-border bg-card p-1 shadow-lg">
                  {availableTags.length === 0 ? (
                    <p className="px-2 py-1 text-[11px] text-muted-foreground">
                      Nenhuma tag cadastrada
                    </p>
                  ) : (
                    availableTags.map((t) => {
                      const checked = selectedTags.includes(t)
                      return (
                        <button
                          key={t}
                          type="button"
                          onClick={() => toggleTag(t)}
                          className="flex w-full items-center gap-2 rounded px-2 py-1 text-left text-[11px] font-semibold uppercase tracking-wide text-foreground hover:bg-muted"
                        >
                          <span className={`flex size-3 items-center justify-center rounded border ${checked ? "border-primary bg-primary text-primary-foreground" : "border-border"}`}>
                            {checked && <Check className="size-2" />}
                          </span>
                          {t}
                        </button>
                      )
                    })
                  )}
                </div>
              </>
            )}
          </div>

          <label className="flex h-8 w-full items-center gap-1.5 rounded-md border border-input bg-background px-2.5 sm:w-[180px]">
            <Search className="size-3 text-muted-foreground" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Buscar..."
              className="w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>

          {canCreateFlow ? (
            <button
              type="button"
              onClick={() => setShowNewModal(true)}
              className="inline-flex h-8 items-center justify-center gap-1 rounded-md bg-foreground px-3 text-xs font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Plus className="size-3.5" />
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
          <div className="grid min-w-[960px] grid-cols-[1fr_140px_200px_110px_110px_110px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Fluxo</span>
            <span className="text-left">Sistema</span>
            <span className="text-left">Tags</span>
            <span className="text-left">Status</span>
            <span className="text-left">Atualizado</span>
            <span className="text-right">Ações</span>
          </div>

          <div className="divide-y divide-border">
            {filtered.map((flow) => (
              <div
                key={flow.id}
                className="grid min-w-[960px] grid-cols-[1fr_140px_200px_110px_110px_110px] items-center px-4 py-4 transition-colors hover:bg-muted/10"
              >
                <div className="flex items-center gap-3">
                  <div className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                    <Workflow className="size-4" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate text-[13px] font-semibold text-foreground">{flow.name}</p>
                    <p className="truncate text-[11px] text-muted-foreground">{flow.description || scopeName}</p>
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

                <div className="flex flex-wrap gap-1">
                  {flow.tags && flow.tags.length > 0 ? (
                    flow.tags.map((t) => (
                      <span
                        key={t}
                        className="inline-flex rounded bg-muted px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground"
                      >
                        {t}
                      </span>
                    ))
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

              {flow.tags && flow.tags.length > 0 && (
                <div className="mt-2 flex flex-wrap gap-1">
                  {flow.tags.map((t) => (
                    <span
                      key={t}
                      className="inline-flex rounded bg-muted px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-muted-foreground"
                    >
                      {t}
                    </span>
                  ))}
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
    {scope === "project" && selectedWorkspace?.id && (
      <TemplatesSection workspaceId={selectedWorkspace.id} />
    )}
    </>
  )
}

export function ContextSectionPage({ scope, section }: ContextSectionPageProps) {
  const { selectedOrganization, selectedWorkspace, selectedProject } = useDashboard()
  const pathname = usePathname()
  const meta = getDashboardSectionMeta(scope, section)

  // Secoes com sub-componentes proprios registram contexto mais rico — aqui apenas o fallback.
  // "visao-geral" e tratado por home/page.tsx. "fluxos"/"conexoes"/"membros" (project) tem sub-componentes.
  const aiContext = useMemo<AIContext | null>(() => {
    const skipSections: string[] = ["visao-geral", "fluxos", "conexoes"]
    if (skipSections.includes(section)) return null
    if (section === "membros" && scope === "project") return null
    return {
      section: "other",
      pathname,
      workspaceId: selectedWorkspace?.id ?? null,
      workspaceName: selectedWorkspace?.name ?? null,
      projectId: selectedProject?.id ?? null,
      projectName: selectedProject?.name ?? null,
      userRole: {
        workspace: (selectedWorkspace?.my_role ?? null) as "VIEWER" | "CONSULTANT" | "MANAGER" | null,
        project: null,
      },
    }
  }, [section, scope, pathname, selectedWorkspace, selectedProject])

  useRegisterAIContext(aiContext)
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

  if (section === "agent-activity") {
    return <AgentActivitySection scope={scope} />
  }

  if (section === "chaves-api") {
    if (scope === "project") return <ProjectApiKeysSection />
    return <AgentKeysSection />
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
