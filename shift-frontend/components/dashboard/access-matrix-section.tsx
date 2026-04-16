"use client"

import { useCallback, useEffect, useState } from "react"
import {
  ArrowDownRight,
  ChevronDown,
  ChevronRight,
  FolderKanban,
  Info,
  Loader2,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  Trash2,
  X,
} from "lucide-react"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useToast } from "@/lib/context/toast-context"
import {
  type AccessMatrixResponse,
  type AccessMatrixUserEntry,
  type AccessMatrixUserProjectRole,
  addProjectMember,
  getWorkspaceAccessMatrix,
  removeProjectMember,
  removeWorkspaceMember,
  updateProjectMemberRole,
  updateWorkspaceMemberRole,
} from "@/lib/auth"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

const ROLE_LABELS: Record<string, string> = {
  OWNER: "Dono",
  MANAGER: "Gerente",
  MEMBER: "Membro",
  GUEST: "Convidado",
  CONSULTANT: "Consultor",
  VIEWER: "Visualizador",
  EDITOR: "Editor",
  CLIENT: "Cliente",
}

const ROLE_COLORS: Record<string, string> = {
  OWNER: "bg-amber-500/10 text-amber-600 dark:text-amber-400",
  MANAGER: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
  CONSULTANT: "bg-purple-500/10 text-purple-600 dark:text-purple-400",
  EDITOR: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  VIEWER: "bg-muted text-muted-foreground",
  MEMBER: "bg-muted text-muted-foreground",
  GUEST: "bg-muted text-muted-foreground",
  CLIENT: "bg-muted text-muted-foreground",
}

const WS_ROLES = [
  { value: "VIEWER", label: "Visualizador" },
  { value: "CONSULTANT", label: "Consultor" },
  { value: "MANAGER", label: "Gerente" },
]

const PROJ_ROLES = [
  { value: "CLIENT", label: "Cliente" },
  { value: "EDITOR", label: "Editor" },
]

const SOURCE_LABEL: Record<string, string> = {
  explicit: "Explícito",
  inherited_org: "Herdado da Org",
  inherited_ws: "Herdado do Workspace",
  none: "Sem acesso",
}

function RoleBadge({
  role,
  inherited,
}: {
  role: string
  inherited?: boolean
}) {
  return (
    <span
      className={`inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium uppercase ${ROLE_COLORS[role] ?? "bg-muted text-muted-foreground"} ${inherited ? "opacity-60" : ""}`}
    >
      {inherited ? <ArrowDownRight className="size-2.5" /> : null}
      {ROLE_LABELS[role] ?? role}
    </span>
  )
}

type EditingCell = {
  userId: string
  scope: "workspace" | "project"
  projectId?: string
  currentRole: string | null
}

export function AccessMatrixSection() {
  const { selectedWorkspace } = useDashboard()
  const toast = useToast()

  const [matrix, setMatrix] = useState<AccessMatrixResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [searchTerm, setSearchTerm] = useState("")
  const [showLegend, setShowLegend] = useState(false)
  const [expandedUserId, setExpandedUserId] = useState<string | null>(null)
  const [editingCell, setEditingCell] = useState<EditingCell | null>(null)
  const [saving, setSaving] = useState(false)

  const loadMatrix = useCallback(async () => {
    if (!selectedWorkspace?.id) return
    setLoading(true)
    try {
      const data = await getWorkspaceAccessMatrix(selectedWorkspace.id)
      setMatrix(data)
    } catch {
      toast.error("Erro", "Falha ao carregar matriz de acesso.")
    } finally {
      setLoading(false)
    }
  }, [selectedWorkspace?.id, toast])

  useEffect(() => {
    loadMatrix()
  }, [loadMatrix])

  const handleWsRoleChange = async (user: AccessMatrixUserEntry, newRole: string) => {
    if (!selectedWorkspace?.id) return
    setSaving(true)
    try {
      if (newRole === "__remove__") {
        await removeWorkspaceMember(selectedWorkspace.id, user.user_id)
        toast.success("Removido", `Acesso de ${user.email} ao workspace removido.`)
      } else {
        await updateWorkspaceMemberRole(selectedWorkspace.id, user.user_id, newRole)
        toast.success("Atualizado", `Papel de ${user.email} no workspace alterado.`)
      }
      setEditingCell(null)
      await loadMatrix()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao alterar papel.")
    } finally {
      setSaving(false)
    }
  }

  const handleProjRoleChange = async (
    user: AccessMatrixUserEntry,
    projectId: string,
    projRole: AccessMatrixUserProjectRole,
    newRole: string,
  ) => {
    setSaving(true)
    try {
      if (newRole === "__remove__") {
        await removeProjectMember(projectId, user.user_id)
        toast.success("Removido", `Acesso explícito de ${user.email} removido do projeto.`)
      } else if (projRole.explicit_role) {
        await updateProjectMemberRole(projectId, user.user_id, newRole)
        toast.success("Atualizado", `Papel de ${user.email} no projeto alterado.`)
      } else {
        await addProjectMember(projectId, { email: user.email, role: newRole })
        toast.success("Adicionado", `${user.email} adicionado ao projeto.`)
      }
      setEditingCell(null)
      await loadMatrix()
    } catch (err) {
      toast.error("Erro", err instanceof Error ? err.message : "Falha ao alterar papel.")
    } finally {
      setSaving(false)
    }
  }

  if (!selectedWorkspace?.id) {
    return (
      <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border bg-card">
        <p className="text-sm text-muted-foreground">
          Selecione um workspace para ver a matriz de acesso.
        </p>
      </div>
    )
  }

  const filteredUsers =
    matrix?.users.filter(
      (u) =>
        !searchTerm ||
        u.email.toLowerCase().includes(searchTerm.toLowerCase()) ||
        (u.full_name && u.full_name.toLowerCase().includes(searchTerm.toLowerCase())),
    ) ?? []

  const projects = matrix?.projects ?? []

  function countAccessibleProjects(user: AccessMatrixUserEntry): number {
    return user.project_roles.filter((pr) => pr.effective_role !== null).length
  }

  function toggleExpand(userId: string) {
    setExpandedUserId((prev) => (prev === userId ? null : userId))
    setEditingCell(null)
  }

  return (
    <section className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-2">
          <ShieldCheck className="size-4 text-muted-foreground" />
          <span className="text-sm font-medium text-foreground">Controle de Acesso</span>
          {matrix ? (
            <span className="text-xs text-muted-foreground">
              {matrix.users.length} {matrix.users.length === 1 ? "usuário" : "usuários"} |{" "}
              {projects.length} {projects.length === 1 ? "projeto" : "projetos"}
            </span>
          ) : null}
        </div>

        <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
          <label className="flex h-9 w-full items-center gap-2 rounded-md border border-input bg-background px-3 sm:w-[220px]">
            <Search className="size-4 text-muted-foreground" />
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Buscar usuário..."
              className="w-full bg-transparent text-sm text-foreground outline-none placeholder:text-muted-foreground"
            />
          </label>
          <button
            type="button"
            onClick={() => setShowLegend((v) => !v)}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            <Info className="size-4" />
            Legenda
          </button>
          <button
            type="button"
            onClick={loadMatrix}
            disabled={loading}
            className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-border bg-background px-3 text-sm text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            <RefreshCw className={`size-4 ${loading ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Legend */}
      {showLegend ? (
        <div className="flex flex-wrap items-center gap-4 rounded-xl border border-border bg-card px-4 py-3 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <span className="inline-flex rounded bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-blue-600 dark:text-blue-400">
              GERENTE
            </span>
            <span>Papel explícito</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="inline-flex items-center gap-1 rounded bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium uppercase text-blue-600 opacity-60 dark:text-blue-400">
              <ArrowDownRight className="size-2.5" />
              GERENTE
            </span>
            <span>Papel herdado (Org/Workspace)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="text-muted-foreground/50">—</span>
            <span>Sem acesso</span>
          </div>
          <div className="ml-2 border-l border-border pl-3 text-[11px]">
            Somente <strong>Gerente+</strong> herda acesso a todos os projetos. Consultores e
            Visualizadores precisam de acesso explícito por projeto.
          </div>
        </div>
      ) : null}

      {/* Matrix */}
      {loading ? (
        <div className="flex h-32 items-center justify-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" /> Carregando matriz...
        </div>
      ) : !matrix || matrix.users.length === 0 ? (
        <div className="flex h-32 items-center justify-center rounded-xl border border-dashed border-border bg-card">
          <p className="text-sm text-muted-foreground">Nenhum usuário encontrado.</p>
        </div>
      ) : (
        <div className="overflow-auto rounded-xl border border-border bg-card shadow-sm">
          {/* Header */}
          <div className="grid grid-cols-[minmax(240px,1fr)_100px_140px_160px] items-center border-b border-border px-4 py-3 text-[10px] font-bold uppercase tracking-wider text-muted-foreground">
            <span>Usuário</span>
            <span className="text-center">Org</span>
            <span className="text-center">Workspace</span>
            <span className="text-center">Projetos</span>
          </div>

          {/* Rows */}
          <div className="divide-y divide-border">
            {filteredUsers.map((user) => {
              const isExpanded = expandedUserId === user.user_id
              const accessCount = countAccessibleProjects(user)
              const isManager =
                user.ws_effective_role === "MANAGER" ||
                user.org_role === "OWNER" ||
                user.org_role === "MANAGER"

              return (
                <div key={user.user_id}>
                  {/* Main row */}
                  <button
                    type="button"
                    onClick={() => toggleExpand(user.user_id)}
                    className="grid w-full grid-cols-[minmax(240px,1fr)_100px_140px_160px] items-center px-4 py-3 text-left transition-colors hover:bg-muted/10"
                  >
                    {/* User */}
                    <div className="flex items-center gap-2.5">
                      <div className="flex size-3.5 shrink-0 items-center justify-center text-muted-foreground">
                        {isExpanded ? (
                          <ChevronDown className="size-3.5" />
                        ) : (
                          <ChevronRight className="size-3.5" />
                        )}
                      </div>
                      <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary">
                        {user.email[0].toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <p className="truncate text-[13px] font-medium text-foreground">
                          {user.full_name ?? user.email}
                        </p>
                        {user.full_name ? (
                          <p className="truncate text-[11px] text-muted-foreground">{user.email}</p>
                        ) : null}
                      </div>
                    </div>

                    {/* Org role */}
                    <div className="text-center">
                      {user.org_role ? (
                        <RoleBadge role={user.org_role} />
                      ) : (
                        <span className="text-xs text-muted-foreground/50">—</span>
                      )}
                    </div>

                    {/* Workspace role */}
                    <div className="text-center">
                      {user.ws_effective_role ? (
                        <RoleBadge
                          role={user.ws_effective_role}
                          inherited={user.ws_role_source !== "explicit"}
                        />
                      ) : (
                        <span className="text-xs text-muted-foreground/50">—</span>
                      )}
                    </div>

                    {/* Project count */}
                    <div className="text-center">
                      {isManager ? (
                        <span className="inline-flex items-center gap-1 rounded bg-blue-500/10 px-2 py-0.5 text-[10px] font-medium text-blue-600 opacity-60 dark:text-blue-400">
                          <ArrowDownRight className="size-2.5" />
                          Todos ({projects.length})
                        </span>
                      ) : accessCount > 0 ? (
                        <span className="inline-flex rounded bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-600 dark:text-emerald-400">
                          {accessCount} {accessCount === 1 ? "projeto" : "projetos"}
                        </span>
                      ) : (
                        <span className="text-[10px] text-muted-foreground/50">Nenhum</span>
                      )}
                    </div>
                  </button>

                  {/* Expanded: project details */}
                  {isExpanded ? (
                    <div className="border-t border-border/50 bg-muted/5 px-4 py-3">
                      {/* WS role editing */}
                      <div className="mb-3 flex items-center gap-3">
                        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Papel no Workspace:
                        </span>
                        {editingCell?.userId === user.user_id &&
                        editingCell.scope === "workspace" ? (
                          <div className="flex items-center gap-1.5">
                            <Select
                              value={editingCell.currentRole ?? ""}
                              onValueChange={(val) => handleWsRoleChange(user, val)}
                              disabled={saving}
                            >
                              <SelectTrigger className="h-7 w-[140px] bg-background text-xs">
                                <SelectValue placeholder="Selecione" />
                              </SelectTrigger>
                              <SelectContent>
                                {WS_ROLES.map((r) => (
                                  <SelectItem key={r.value} value={r.value}>
                                    {r.label}
                                  </SelectItem>
                                ))}
                                {user.ws_explicit_role ? (
                                  <SelectItem value="__remove__" className="text-destructive">
                                    Remover
                                  </SelectItem>
                                ) : null}
                              </SelectContent>
                            </Select>
                            {saving ? (
                              <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
                            ) : (
                              <button
                                type="button"
                                onClick={() => setEditingCell(null)}
                                className="rounded p-1 text-muted-foreground hover:bg-muted"
                              >
                                <X className="size-3" />
                              </button>
                            )}
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() =>
                              setEditingCell({
                                userId: user.user_id,
                                scope: "workspace",
                                currentRole: user.ws_explicit_role ?? user.ws_effective_role ?? "VIEWER",
                              })
                            }
                            className="rounded px-1.5 py-0.5 transition-colors hover:bg-accent"
                          >
                            {user.ws_effective_role ? (
                              <RoleBadge
                                role={user.ws_effective_role}
                                inherited={user.ws_role_source !== "explicit"}
                              />
                            ) : (
                              <span className="text-xs text-muted-foreground">Definir papel</span>
                            )}
                          </button>
                        )}
                        {user.ws_role_source !== "explicit" && user.ws_effective_role ? (
                          <span className="text-[10px] text-muted-foreground">
                            ({SOURCE_LABEL[user.ws_role_source]})
                          </span>
                        ) : null}
                      </div>

                      {/* Project list */}
                      <div className="space-y-1">
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                          Projetos ({projects.length})
                        </p>
                        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
                          {projects.map((proj) => {
                            const projRole = user.project_roles.find(
                              (pr) => pr.project_id === proj.project_id,
                            )
                            const isEditingThis =
                              editingCell?.userId === user.user_id &&
                              editingCell.scope === "project" &&
                              editingCell.projectId === proj.project_id

                            return (
                              <div
                                key={proj.project_id}
                                className="flex items-center justify-between rounded-lg border border-border bg-background/70 px-3 py-2"
                              >
                                <div className="flex items-center gap-2 min-w-0">
                                  <FolderKanban className="size-3.5 shrink-0 text-muted-foreground" />
                                  <span className="truncate text-[12px] font-medium text-foreground">
                                    {proj.project_name}
                                  </span>
                                </div>

                                <div className="flex items-center gap-1.5 shrink-0 ml-2">
                                  {isEditingThis ? (
                                    <>
                                      <Select
                                        value={editingCell.currentRole ?? ""}
                                        onValueChange={(val) =>
                                          handleProjRoleChange(
                                            user,
                                            proj.project_id,
                                            projRole ?? {
                                              project_id: proj.project_id,
                                              explicit_role: null,
                                              effective_role: null,
                                              source: "none",
                                            },
                                            val,
                                          )
                                        }
                                        disabled={saving}
                                      >
                                        <SelectTrigger className="h-7 w-[110px] bg-background text-xs">
                                          <SelectValue placeholder="Papel" />
                                        </SelectTrigger>
                                        <SelectContent>
                                          {PROJ_ROLES.map((r) => (
                                            <SelectItem key={r.value} value={r.value}>
                                              {r.label}
                                            </SelectItem>
                                          ))}
                                          {projRole?.explicit_role ? (
                                            <SelectItem
                                              value="__remove__"
                                              className="text-destructive"
                                            >
                                              Remover
                                            </SelectItem>
                                          ) : null}
                                        </SelectContent>
                                      </Select>
                                      {saving ? (
                                        <Loader2 className="size-3.5 animate-spin text-muted-foreground" />
                                      ) : (
                                        <button
                                          type="button"
                                          onClick={() => setEditingCell(null)}
                                          className="rounded p-1 text-muted-foreground hover:bg-muted"
                                        >
                                          <X className="size-3" />
                                        </button>
                                      )}
                                    </>
                                  ) : projRole?.effective_role ? (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setEditingCell({
                                          userId: user.user_id,
                                          scope: "project",
                                          projectId: proj.project_id,
                                          currentRole:
                                            projRole.explicit_role ?? projRole.effective_role,
                                        })
                                      }
                                      className="rounded px-0.5 py-0.5 transition-colors hover:bg-accent"
                                      title={SOURCE_LABEL[projRole.source]}
                                    >
                                      <RoleBadge
                                        role={projRole.effective_role}
                                        inherited={projRole.source !== "explicit"}
                                      />
                                    </button>
                                  ) : (
                                    <button
                                      type="button"
                                      onClick={() =>
                                        setEditingCell({
                                          userId: user.user_id,
                                          scope: "project",
                                          projectId: proj.project_id,
                                          currentRole: "CLIENT",
                                        })
                                      }
                                      className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-[10px] font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                                    >
                                      <Plus className="size-3" />
                                      Adicionar
                                    </button>
                                  )}
                                </div>
                              </div>
                            )
                          })}
                        </div>
                      </div>
                    </div>
                  ) : null}
                </div>
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}
