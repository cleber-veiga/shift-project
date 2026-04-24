"use client"

import { useCallback, useEffect, useMemo, useState } from "react"
import { useRegisterAIContext } from "@/lib/context/ai-context"
import type { AIContext } from "@/lib/types/ai-context"
import { useRouter } from "next/navigation"
import {
  Building2,
  Database,
  FlaskConical,
  Globe,
  Grid2X2,
  List,
  Lock,
  Pencil,
  Play,
  Plus,
  Search,
  Trash2,
  Eye,
  EyeOff,
} from "lucide-react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Tooltip } from "@/components/ui/tooltip"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useToast } from "@/lib/context/toast-context"
import { getStoredSession } from "@/lib/auth"
import {
  type Connection,
  type ConnectionType,
  type CreateConnectionPayload,
  type UpdateConnectionPayload,
  type WorkspacePlayer,
  listWorkspaceConnections,
  listProjectConnections,
  listWorkspacePlayers,
  createConnection,
  updateConnection,
  deleteConnection,
  testConnection,
} from "@/lib/auth"
import type { DashboardScope } from "@/lib/dashboard-navigation"
import { hasWorkspacePermission } from "@/lib/permissions"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"
import { MorphLoader } from "@/components/ui/morph-loader"
import { ConnectionFormModal } from "@/components/dashboard/connection-form-modal"

const DB_TYPE_LABELS: Record<ConnectionType, string> = {
  oracle: "Oracle",
  postgresql: "PostgreSQL",
  firebird: "Firebird",
  sqlserver: "SQL Server",
  mysql: "MySQL",
}

const DB_TYPE_COLORS: Record<ConnectionType, string> = {
  oracle: "bg-red-500/10 text-red-600 dark:text-red-400",
  postgresql: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  firebird: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  sqlserver: "bg-indigo-500/10 text-indigo-600 dark:text-indigo-400",
  mysql: "bg-cyan-500/10 text-cyan-600 dark:text-cyan-400",
}

interface ConnectionsSectionProps {
  scope: DashboardScope
}

export function ConnectionsSection({ scope }: ConnectionsSectionProps) {
  const { selectedWorkspace, selectedProject } = useDashboard()
  const router = useRouter()
  const toast = useToast()
  const currentUserId = getStoredSession()?.user.id ?? null

  const wsRole = selectedWorkspace?.my_role ?? null
  const canCreate = scope === "space" ? hasWorkspacePermission(wsRole, "MANAGER") : true
  const canUsePlayground = scope === "space" ? hasWorkspacePermission(wsRole, "CONSULTANT") : true

  const [connections, setConnections] = useState<Connection[]>([])
  const [players, setPlayers] = useState<WorkspacePlayer[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState("")

  const aiContext = useMemo<AIContext | null>(() => {
    if (loading) return null
    return {
      section: "connections",
      scope: scope === "space" ? "workspace" : "project",
      workspaceId: selectedWorkspace?.id ?? null,
      workspaceName: selectedWorkspace?.name ?? null,
      projectId: selectedProject?.id ?? null,
      projectName: selectedProject?.name ?? null,
      userRole: {
        workspace: (selectedWorkspace?.my_role ?? null) as "VIEWER" | "CONSULTANT" | "MANAGER" | null,
        project: null,
      },
      connections: connections.map((c) => ({
        id: c.id,
        name: c.name,
        type: c.type,
        isPublic: c.is_public,
      })),
    }
  }, [loading, connections, scope, selectedWorkspace, selectedProject])

  useRegisterAIContext(aiContext)
  const [search, setSearch] = useState("")
  const [view, setView] = useState<"list" | "card">("list")
  const [typeFilter, setTypeFilter] = useState<"todos" | ConnectionType>("todos")

  // Modal states
  const [formOpen, setFormOpen] = useState(false)
  const [editingConnection, setEditingConnection] = useState<Connection | null>(null)

  // Delete confirm
  const [deleteTarget, setDeleteTarget] = useState<Connection | null>(null)
  const [deleting, setDeleting] = useState(false)

  // Test connection
  const [testingId, setTestingId] = useState<string | null>(null)

  const loadConnections = useCallback(async () => {
    setLoading(true)
    setError("")
    try {
      const wsId = selectedWorkspace?.id ?? selectedProject?.workspace_id
      const [connectionsData, playersData] = await Promise.all([
        scope === "space" && selectedWorkspace
          ? listWorkspaceConnections(selectedWorkspace.id, { size: 200 }).then((r) => r.items)
          : scope === "project" && selectedProject
            ? listProjectConnections(selectedProject.id, { size: 200 }).then((r) => r.items)
            : Promise.resolve([] as Connection[]),
        wsId ? listWorkspacePlayers(wsId) : Promise.resolve([] as WorkspacePlayer[]),
      ])
      setConnections(connectionsData)
      setPlayers(playersData)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Erro ao carregar conexões.")
    } finally {
      setLoading(false)
    }
  }, [scope, selectedWorkspace, selectedProject])

  useEffect(() => {
    void loadConnections()
  }, [loadConnections])

  const filtered = useMemo(() => {
    let result = connections
    if (typeFilter !== "todos") {
      result = result.filter((c) => c.type === typeFilter)
    }
    if (search.trim()) {
      const term = search.toLowerCase()
      result = result.filter(
        (c) =>
          c.name.toLowerCase().includes(term) ||
          c.type.toLowerCase().includes(term) ||
          c.host.toLowerCase().includes(term) ||
          c.database.toLowerCase().includes(term)
      )
    }
    return result
  }, [connections, search, typeFilter])

  function isInherited(conn: Connection) {
    return scope === "project" && conn.workspace_id !== null
  }

  /** Pode editar/excluir: não é herdada, tem role suficiente, e (é pública OU criada pelo user atual) */
  function canEdit(conn: Connection) {
    if (isInherited(conn)) return false
    if (!canCreate) return false
    return conn.is_public || conn.created_by_id === currentUserId
  }

  async function handleDelete() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteConnection(deleteTarget.id)
      setDeleteTarget(null)
      await loadConnections()
      toast.success("Conexão excluída", "A conexão foi removida com sucesso.")
    } catch (err) {
      toast.error("Erro ao excluir", err instanceof Error ? err.message : "Erro ao excluir conexão.")
    } finally {
      setDeleting(false)
    }
  }

  async function handleTest(conn: Connection) {
    setTestingId(conn.id)
    try {
      const result = await testConnection(conn.id)
      if (result.success) {
        toast.success("Conexão bem-sucedida", result.message)
      } else {
        toast.error("Falha na conexão", result.message)
      }
    } catch (err) {
      toast.error("Falha na conexão", err instanceof Error ? err.message : "Erro ao testar conexão.")
    } finally {
      setTestingId(null)
    }
  }

  function handleOpenCreate() {
    setEditingConnection(null)
    setFormOpen(true)
  }

  function handleOpenEdit(conn: Connection) {
    setEditingConnection(conn)
    setFormOpen(true)
  }

  async function handleFormSubmit(
    payload: CreateConnectionPayload | UpdateConnectionPayload
  ) {
    if (editingConnection) {
      await updateConnection(editingConnection.id, payload as UpdateConnectionPayload)
      toast.success("Conexão atualizada", "As alterações foram salvas com sucesso.")
    } else {
      await createConnection(payload as CreateConnectionPayload)
      toast.success("Conexão criada", "A conexão foi cadastrada com sucesso.")
    }
    setFormOpen(false)
    setEditingConnection(null)
    await loadConnections()
  }

  function formatDate(iso: string) {
    try {
      return new Date(iso).toLocaleDateString("pt-BR")
    } catch {
      return iso
    }
  }

  if (loading) {
    return (
      <section className="flex items-center justify-center py-20">
        <MorphLoader className="size-5" />
      </section>
    )
  }

  return (
    <section className="space-y-3">
      {/* Toolbar */}
      <div className="flex flex-col gap-2 rounded-lg border border-border bg-card p-2 sm:flex-row sm:items-center sm:justify-between">
        {/* Toggle Lista / Card */}
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
          {/* Filtro por tipo */}
          <Select value={typeFilter} onValueChange={(v) => setTypeFilter(v as "todos" | ConnectionType)}>
            <SelectTrigger size="sm" className="w-full min-w-36 bg-background text-xs sm:w-[140px]">
              <SelectValue placeholder="Todos os Tipos" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="todos">Todos os Tipos</SelectItem>
              <SelectItem value="postgresql">PostgreSQL</SelectItem>
              <SelectItem value="sqlserver">SQL Server</SelectItem>
              <SelectItem value="oracle">Oracle</SelectItem>
              <SelectItem value="mysql">MySQL</SelectItem>
              <SelectItem value="firebird">Firebird</SelectItem>
            </SelectContent>
          </Select>

          <label className="flex h-8 w-full items-center gap-1.5 rounded-md border border-input bg-background px-2.5 sm:w-[180px]">
            <Search className="size-3 text-muted-foreground" />
            <input
              type="text"
              placeholder="Buscar..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-transparent text-xs text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>

          {canCreate ? (
            <button
              type="button"
              onClick={handleOpenCreate}
              className="inline-flex h-8 items-center justify-center gap-1 rounded-md bg-foreground px-3 text-xs font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Plus className="size-3.5" />
              Nova Conexão
            </button>
          ) : null}
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-500/20 bg-red-500/10 px-4 py-3 text-sm text-red-200">
          {error}
        </div>
      )}

      {/* Empty state */}
      {filtered.length === 0 && !error ? (
        <div className="rounded-2xl border border-dashed border-border bg-card/60 p-8 text-center">
          <Database className="mx-auto size-10 text-muted-foreground/40" />
          <p className="mt-3 text-base font-semibold text-foreground">
            Nenhuma conexão encontrada
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            {search || typeFilter !== "todos"
              ? "Nenhum resultado para os filtros aplicados."
              : "Cadastre sua primeira conexão de banco de dados."}
          </p>
          {!search && typeFilter === "todos" && canCreate && (
            <button
              type="button"
              onClick={handleOpenCreate}
              className="mt-4 inline-flex h-9 items-center justify-center gap-1.5 rounded-md bg-foreground px-4 text-sm font-semibold text-background transition-opacity hover:opacity-90"
            >
              <Plus className="size-4" />
              Nova Conexão
            </button>
          )}
        </div>
      ) : view === "list" ? (
        /* ── Vista lista ── */
        <div className="overflow-x-auto rounded-xl border border-border bg-card shadow-sm">
          <div className="grid min-w-[820px] grid-cols-[1fr_110px_120px_120px_110px_148px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Conexão</span>
            <span className="text-left">Tipo</span>
            <span className="text-left">Host</span>
            <span className="text-left">Sistema</span>
            <span className="text-left">Visibilidade</span>
            <span className="text-right">Ações</span>
          </div>

          <div className="divide-y divide-border">
            {filtered.map((conn) => {
              const inherited = isInherited(conn)
              const editable = canEdit(conn)
              const player = conn.player_id ? players.find((p) => p.id === conn.player_id) : null
              return (
                <div
                  key={conn.id}
                  className="grid min-w-[820px] grid-cols-[1fr_110px_120px_120px_110px_148px] items-center px-4 py-4 transition-colors hover:bg-muted/10"
                >
                  <div className="flex items-center gap-3">
                    <div className="flex size-8 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <Database className="size-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <p className="truncate text-[13px] font-semibold text-foreground">{conn.name}</p>
                        {inherited && (
                          <span className="inline-flex items-center gap-1 rounded bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-medium text-violet-500">
                            <Globe className="size-3" />
                            Compartilhada
                          </span>
                        )}
                      </div>
                      <p className="text-[11px] text-muted-foreground">
                        {conn.username}@{conn.host}:{conn.port}
                      </p>
                    </div>
                  </div>

                  <div>
                    <span className={`inline-flex rounded px-2 py-0.5 text-[10px] font-medium ${DB_TYPE_COLORS[conn.type]}`}>
                      {DB_TYPE_LABELS[conn.type]}
                    </span>
                  </div>

                  <p className="truncate text-[12px] text-foreground">{conn.host}:{conn.port}</p>

                  <div>
                    {player ? (
                      <span className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                        <Building2 className="size-3" />
                        <span className="truncate max-w-[90px]">{player.name}</span>
                      </span>
                    ) : (
                      <span className="text-[11px] text-muted-foreground">—</span>
                    )}
                  </div>

                  <div>
                    {inherited ? (
                      <span className="inline-flex items-center gap-1 rounded bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-500">
                        <Globe className="size-3" />
                        Herdada
                      </span>
                    ) : conn.is_public ? (
                      <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                        <Eye className="size-3" />
                        Pública
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
                        <EyeOff className="size-3" />
                        Privada
                      </span>
                    )}
                  </div>

                  <div className="flex items-center justify-end gap-1">
                    <Tooltip text="Testar conexão">
                      <button
                        type="button"
                        onClick={() => void handleTest(conn)}
                        disabled={testingId === conn.id}
                        className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                        aria-label="Testar conexão"
                      >
                        {testingId === conn.id ? <MorphLoader className="size-4" /> : <Play className="size-4" />}
                      </button>
                    </Tooltip>
                    {canUsePlayground ? (
                      <Tooltip text="Playground">
                        <button
                          type="button"
                          onClick={() => router.push(`/playground/${conn.id}`)}
                          className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          aria-label="Playground"
                        >
                          <FlaskConical className="size-4" />
                        </button>
                      </Tooltip>
                    ) : null}
                    {editable ? (
                      <>
                        <Tooltip text="Editar">
                          <button
                            type="button"
                            onClick={() => handleOpenEdit(conn)}
                            className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                            aria-label="Editar conexão"
                          >
                            <Pencil className="size-4" />
                          </button>
                        </Tooltip>
                        <Tooltip text="Excluir">
                          <button
                            type="button"
                            onClick={() => setDeleteTarget(conn)}
                            className="rounded p-2 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive"
                            aria-label="Excluir conexão"
                          >
                            <Trash2 className="size-4" />
                          </button>
                        </Tooltip>
                      </>
                    ) : (
                      <span className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] text-muted-foreground">
                        <Lock className="size-3" />
                        {inherited ? "Herdada" : "Sem permissão"}
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ) : (
        /* ── Vista card ── */
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
          {filtered.map((conn) => {
            const inherited = isInherited(conn)
            const editable = canEdit(conn)
            const player = conn.player_id ? players.find((p) => p.id === conn.player_id) : null
            return (
              <article
                key={conn.id}
                className="rounded-xl border border-border bg-card p-4 shadow-sm transition-colors hover:bg-muted/10"
              >
                {/* Header: ícone + nome + tipo */}
                <div className="flex items-start justify-between gap-3">
                  <div className="flex items-start gap-3 min-w-0">
                    <div className="mt-0.5 flex size-9 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
                      <Database className="size-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <h3 className="truncate text-sm font-semibold text-foreground">{conn.name}</h3>
                        {inherited && (
                          <span className="inline-flex items-center gap-1 rounded bg-violet-500/10 px-1.5 py-0.5 text-[10px] font-medium text-violet-500">
                            <Globe className="size-3" />
                            Compartilhada
                          </span>
                        )}
                      </div>
                      <p className="mt-0.5 truncate text-[11px] text-muted-foreground">
                        {conn.username}@{conn.host}:{conn.port}
                      </p>
                    </div>
                  </div>
                  <span className={`shrink-0 inline-flex rounded px-2 py-0.5 text-[10px] font-medium ${DB_TYPE_COLORS[conn.type]}`}>
                    {DB_TYPE_LABELS[conn.type]}
                  </span>
                </div>

                {/* Badges: visibilidade + sistema */}
                <div className="mt-3 flex flex-wrap items-center gap-2">
                  {inherited ? (
                    <span className="inline-flex items-center gap-1 rounded bg-violet-500/10 px-2 py-0.5 text-[10px] font-medium text-violet-500">
                      <Globe className="size-3" />
                      Herdada
                    </span>
                  ) : conn.is_public ? (
                    <span className="inline-flex items-center gap-1 rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                      <Eye className="size-3" />
                      Pública
                    </span>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded bg-amber-500/10 px-2 py-0.5 text-[10px] font-medium text-amber-600 dark:text-amber-400">
                      <EyeOff className="size-3" />
                      Privada
                    </span>
                  )}
                  {player && (
                    <span className="inline-flex items-center gap-1 rounded bg-primary/10 px-2 py-0.5 text-[10px] font-medium text-primary">
                      <Building2 className="size-3" />
                      <span className="truncate max-w-[100px]">{player.name}</span>
                    </span>
                  )}
                </div>

                {/* Footer: ações */}
                <div className="mt-3 flex items-center justify-end gap-1 border-t border-border pt-3">
                  <Tooltip text="Testar conexão">
                    <button
                      type="button"
                      onClick={() => void handleTest(conn)}
                      disabled={testingId === conn.id}
                      className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground disabled:opacity-50"
                      aria-label="Testar conexão"
                    >
                      {testingId === conn.id ? <MorphLoader className="size-4" /> : <Play className="size-4" />}
                    </button>
                  </Tooltip>
                  {canUsePlayground ? (
                    <Tooltip text="Playground">
                      <button
                        type="button"
                        onClick={() => router.push(`/playground/${conn.id}`)}
                        className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                        aria-label="Playground"
                      >
                        <FlaskConical className="size-4" />
                      </button>
                    </Tooltip>
                  ) : null}
                  {editable ? (
                    <>
                      <Tooltip text="Editar">
                        <button
                          type="button"
                          onClick={() => handleOpenEdit(conn)}
                          className="rounded p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                          aria-label="Editar conexão"
                        >
                          <Pencil className="size-4" />
                        </button>
                      </Tooltip>
                      <Tooltip text="Excluir">
                        <button
                          type="button"
                          onClick={() => setDeleteTarget(conn)}
                          className="rounded p-2 text-destructive/70 transition-colors hover:bg-muted hover:text-destructive"
                          aria-label="Excluir conexão"
                        >
                          <Trash2 className="size-4" />
                        </button>
                      </Tooltip>
                    </>
                  ) : (
                    <span className="inline-flex items-center gap-1 rounded px-2 py-1 text-[10px] text-muted-foreground">
                      <Lock className="size-3" />
                      {inherited ? "Herdada" : "Sem permissão"}
                    </span>
                  )}
                </div>
              </article>
            )
          })}
        </div>
      )}

      {/* Delete confirmation */}
      <ConfirmDialog
        open={deleteTarget !== null}
        onOpenChange={(open) => {
          if (!open) setDeleteTarget(null)
        }}
        title="Excluir conexão"
        description={`Tem certeza que deseja excluir "${deleteTarget?.name}"? Esta ação não pode ser desfeita.`}
        confirmText="Excluir"
        confirmVariant="destructive"
        loading={deleting}
        onConfirm={handleDelete}
      />

      {/* Create/Edit modal */}
      <ConnectionFormModal
        open={formOpen}
        onOpenChange={(open) => {
          if (!open) {
            setFormOpen(false)
            setEditingConnection(null)
          }
        }}
        connection={editingConnection}
        scope={scope}
        workspaceId={selectedWorkspace?.id ?? null}
        projectId={selectedProject?.id ?? null}
        onSubmit={handleFormSubmit}
      />
    </section>
  )
}
