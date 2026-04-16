"use client"

import { MorphLoader } from "@/components/ui/morph-loader"
import {
  listOrganizationConglomerates,
  listWorkspacePlayers,
  type Conglomerate,
  type WorkspacePlayer,
} from "@/lib/auth"
import { useDashboard } from "@/lib/context/dashboard-context"
import { dashboardNavigationGroups } from "@/lib/dashboard-navigation"
import { cn } from "@/lib/utils"
import { RoleBadge } from "@/components/dashboard/role-badge"
import { hasWorkspacePermission } from "@/lib/permissions"
import {
  Building2,
  Check,
  ChevronDown,
  FolderKanban,
  Pencil,
  Plus,
  X,
} from "lucide-react"
import Link from "next/link"
import { usePathname } from "next/navigation"
import { useEffect, useRef, useState } from "react"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"

function formatDateInput(value: Date) {
  const year = value.getFullYear()
  const month = `${value.getMonth() + 1}`.padStart(2, "0")
  const day = `${value.getDate()}`.padStart(2, "0")
  return `${year}-${month}-${day}`
}

export function Sidebar() {
  const pathname = usePathname()
  const projectMenuRef = useRef<HTMLDivElement | null>(null)
  const [projectMenuOpen, setProjectMenuOpen] = useState(false)
  const [createProjectOpen, setCreateProjectOpen] = useState(false)
  const [editingProjectId, setEditingProjectId] = useState<string | null>(null)
  const [projectName, setProjectName] = useState("")
  const [projectDescription, setProjectDescription] = useState("")
  const [projectConglomerateId, setProjectConglomerateId] = useState("")
  const [projectCompetitorId, setProjectCompetitorId] = useState("")
  const [availableConglomerates, setAvailableConglomerates] = useState<Conglomerate[]>([])
  const [availableCompetitors, setAvailableCompetitors] = useState<WorkspacePlayer[]>([])
  const [isLoadingProjectDependencies, setIsLoadingProjectDependencies] = useState(false)
  const [isCreatingProject, setIsCreatingProject] = useState(false)
  const [createProjectError, setCreateProjectError] = useState("")
  const [projectStartDate, setProjectStartDate] = useState(() => formatDateInput(new Date()))
  const [projectEndDate, setProjectEndDate] = useState(() => {
    const next = new Date()
    next.setDate(next.getDate() + 30)
    return formatDateInput(next)
  })

  const {
    selectedProject,
    selectedOrganization,
    selectedWorkspace,
    availableProjects,
    setSelectedProjectId,
    createProjectAndSelect,
    updateProjectAndRefresh,
  } = useDashboard()

  const canManageWorkspace = hasWorkspacePermission(selectedWorkspace?.my_role, "MANAGER")

  useEffect(() => {
    if (!projectMenuOpen) return
    function handleClickOutside(event: MouseEvent) {
      if (projectMenuRef.current && !projectMenuRef.current.contains(event.target as Node)) {
        setProjectMenuOpen(false)
      }
    }
    document.addEventListener("mousedown", handleClickOutside)
    return () => document.removeEventListener("mousedown", handleClickOutside)
  }, [projectMenuOpen])

  const handleProjectSelect = (projectId: string) => {
    setSelectedProjectId(projectId)
    setProjectMenuOpen(false)
  }

  const handleProjectEdit = (projectId: string) => {
    const project = availableProjects.find((item) => item.id === projectId)
    if (!project) return

    setSelectedProjectId(projectId)
    setProjectMenuOpen(false)

    setProjectName(project.name)
    setProjectDescription(project.description ?? "")
    setProjectConglomerateId(project.conglomerate_id ?? "")
    setProjectCompetitorId(project.player_id ?? "")
    setProjectStartDate(project.start_date ?? "")
    setProjectEndDate(project.end_date ?? "")
    setEditingProjectId(project.id)
    setCreateProjectError("")
    setCreateProjectOpen(true)
  }

  useEffect(() => {
    if (!createProjectOpen) return
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isCreatingProject) {
        setEditingProjectId(null)
        setCreateProjectOpen(false)
        setCreateProjectError("")
      }
    }
    document.addEventListener("keydown", onEscape)
    return () => document.removeEventListener("keydown", onEscape)
  }, [createProjectOpen, isCreatingProject])

  useEffect(() => {
    if (!createProjectOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [createProjectOpen])

  useEffect(() => {
    if (!createProjectOpen || !selectedOrganization?.id || !selectedWorkspace?.id) return

    let active = true
    setIsLoadingProjectDependencies(true)

    Promise.all([
      listOrganizationConglomerates(selectedOrganization.id),
      listWorkspacePlayers(selectedWorkspace.id),
    ])
      .then(([conglomerates, competitors]) => {
        if (!active) return
        setAvailableConglomerates(conglomerates)
        setAvailableCompetitors(competitors)

        setProjectConglomerateId((current) => {
          if (current && conglomerates.some((item) => item.id === current)) return current
          return conglomerates[0]?.id ?? ""
        })

        setProjectCompetitorId((current) => {
          if (current && competitors.some((item) => item.id === current)) return current
          return competitors[0]?.id ?? ""
        })
      })
      .catch(() => {
        if (!active) return
        setAvailableConglomerates([])
        setAvailableCompetitors([])
      })
      .finally(() => {
        if (!active) return
        setIsLoadingProjectDependencies(false)
      })

    return () => {
      active = false
    }
  }, [createProjectOpen, selectedOrganization?.id, selectedWorkspace?.id])

  const openCreateProject = () => {
    setProjectMenuOpen(false)
    setEditingProjectId(null)
    setProjectName("")
    setProjectDescription("")
    setProjectConglomerateId("")
    setProjectCompetitorId("")
    setProjectStartDate(formatDateInput(new Date()))
    const next = new Date()
    next.setDate(next.getDate() + 30)
    setProjectEndDate(formatDateInput(next))
    setCreateProjectError("")
    setCreateProjectOpen(true)
  }

  const closeCreateProject = () => {
    if (isCreatingProject) return
    setEditingProjectId(null)
    setCreateProjectError("")
    setCreateProjectOpen(false)
  }

  const canCreateProject =
    projectName.trim().length >= 2 &&
    !!projectConglomerateId &&
    !!projectCompetitorId &&
    !!projectStartDate &&
    !!projectEndDate &&
    !!selectedWorkspace?.id

  const handleCreateProject = async (event: React.FormEvent) => {
    event.preventDefault()

    if (!selectedWorkspace?.id) {
      setCreateProjectError("Selecione um workspace primeiro.")
      return
    }

    if (projectEndDate < projectStartDate) {
      setCreateProjectError("A data final deve ser maior ou igual a data inicial.")
      return
    }

    if (!canCreateProject) return

    setIsCreatingProject(true)
    setCreateProjectError("")

    try {
      if (editingProjectId) {
        await updateProjectAndRefresh({
          project_id: editingProjectId,
          workspace_id: selectedWorkspace.id,
          name: projectName.trim(),
          player_id: projectCompetitorId,
          conglomerate_id: projectConglomerateId,
          start_date: projectStartDate,
          end_date: projectEndDate,
          description: projectDescription.trim() ? projectDescription.trim() : null,
        })
      } else {
        await createProjectAndSelect({
          workspace_id: selectedWorkspace.id,
          name: projectName.trim(),
          player_id: projectCompetitorId,
          conglomerate_id: projectConglomerateId,
          start_date: projectStartDate,
          end_date: projectEndDate,
          description: projectDescription.trim() ? projectDescription.trim() : null,
        })
        setProjectName("")
        setProjectDescription("")
      }
      setEditingProjectId(null)
      setCreateProjectOpen(false)
    } catch (err) {
      setCreateProjectError(
        err instanceof Error
          ? err.message
          : editingProjectId
            ? "Falha ao editar projeto."
            : "Falha ao cadastrar projeto."
      )
    } finally {
      setIsCreatingProject(false)
    }
  }

  const isItemActive = (href: string) => {
    if (href === "/home") return pathname === "/home"
    return pathname.startsWith(href)
  }

  const hasSelectedProject = !!selectedProject

  return (
    <aside className="hidden w-64 border-r border-border bg-card/88 lg:flex lg:flex-col">
      <div className="border-b border-border px-4 py-3">
        <Link href="/home" className="inline-flex items-center gap-2 rounded-md px-0.5 py-0.5">
          <div className="inline-flex size-8 items-center justify-center rounded-md bg-gradient-to-br from-indigo-500 to-violet-600 shadow-sm">
            <Building2 className="size-4 text-white" />
          </div>
          <span className="text-base font-semibold">SHIFT</span>
        </Link>
      </div>

      <div ref={projectMenuRef} className="relative border-b border-border px-4 py-3">
        <button
          type="button"
          onClick={() => setProjectMenuOpen((current) => !current)}
          className="inline-flex w-full items-center gap-2 rounded-xl border border-border bg-background/80 px-2.5 py-1.5 text-left text-xs shadow-sm transition-colors hover:bg-accent/70"
        >
          <FolderKanban className="size-4 text-muted-foreground" />
          <div className="min-w-0 flex-1 leading-tight">
            <p className="truncate font-medium">{selectedProject?.name ?? "Sem projeto"}</p>
            {selectedOrganization?.role ? (
              <RoleBadge role={selectedOrganization.role} />
            ) : (
              <p className="text-muted-foreground">Membro</p>
            )}
          </div>
          <ChevronDown className="size-4 text-muted-foreground" />
        </button>

        {projectMenuOpen ? (
          <div className="absolute left-4 top-[calc(100%-2px)] z-50 mt-2 min-w-[calc(100%-2rem)] w-max max-w-xs rounded-xl border border-border bg-card p-2 shadow-lg">
            <p className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
              Projetos
            </p>
            <div className="max-h-56 space-y-1 overflow-auto">
              {availableProjects.map((project) => (
                <div
                  key={project.id}
                  className="flex items-center gap-1 rounded-md px-1 py-1 hover:bg-accent"
                >
                  <button
                    type="button"
                    onClick={() => handleProjectSelect(project.id)}
                    className="flex min-w-0 flex-1 items-center justify-between rounded-md px-1 py-1 text-left"
                  >
                    <div className="min-w-0">
                      <p className="truncate text-sm font-medium">{project.name}</p>
                      {selectedOrganization?.role ? (
                        <RoleBadge role={selectedOrganization.role} />
                      ) : null}
                    </div>
                    {selectedProject?.id === project.id ? <Check className="size-4 text-primary" /> : null}
                  </button>
                  {canManageWorkspace ? (
                    <button
                      type="button"
                      onClick={(event) => {
                        event.stopPropagation()
                        handleProjectEdit(project.id)
                      }}
                      className="inline-flex size-7 items-center justify-center rounded-md text-muted-foreground transition hover:bg-background hover:text-foreground"
                      aria-label={`Editar projeto ${project.name}`}
                      title="Editar projeto"
                    >
                      <Pencil className="size-3.5" />
                    </button>
                  ) : null}
                </div>
              ))}
              {availableProjects.length === 0 ? (
                <p className="px-2 py-2 text-sm text-muted-foreground">Sem projetos neste workspace.</p>
              ) : null}
            </div>
            {canManageWorkspace ? (
              <div className="mt-1 border-t border-border pt-1">
                <button
                  type="button"
                  onClick={openCreateProject}
                  disabled={!selectedWorkspace?.id}
                  className="inline-flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-primary hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Plus className="size-4" />
                  Criar novo projeto
                </button>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>

      <nav className="flex-1 space-y-6 overflow-y-auto px-4 py-4">
        {dashboardNavigationGroups.map((group) => (
          <section key={group.key}>
            <p className="mb-2 px-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60">
              {group.title}
            </p>
            <div className="space-y-1">
              {group.items.map((item) => {
                if (group.key === "space" && item.minWorkspaceRole && !hasWorkspacePermission(selectedWorkspace?.my_role, item.minWorkspaceRole)) {
                  return null
                }
                const disabled = group.key === "project" && !hasSelectedProject
                const active = isItemActive(item.href)
                const itemClassName = cn(
                  "flex w-full items-center gap-3 rounded-xl px-3 py-2 text-sm transition-colors",
                  disabled
                    ? "cursor-not-allowed text-muted-foreground/45"
                    : active
                      ? "border border-border/80 bg-secondary font-semibold text-foreground shadow-sm"
                      : "text-muted-foreground hover:bg-accent hover:text-foreground"
                )

                const iconClassName = cn(
                  "size-4 transition-colors",
                  disabled ? "text-muted-foreground/45" : active ? "text-foreground" : "text-muted-foreground"
                )

                if (disabled) {
                  return (
                    <div
                      key={`${group.key}-${item.href}`}
                      aria-disabled="true"
                      className={itemClassName}
                    >
                      <item.icon className={iconClassName} />
                      {item.label}
                    </div>
                  )
                }

                return (
                  <Link
                    key={`${group.key}-${item.href}`}
                    href={item.href}
                    className={cn(
                      itemClassName
                    )}
                  >
                    <item.icon className={iconClassName} />
                    {item.label}
                  </Link>
                )
              })}
            </div>
          </section>
        ))}
      </nav>

      {createProjectOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
          role="presentation"
          onClick={closeCreateProject}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label={editingProjectId ? "Editar projeto" : "Cadastrar projeto"}
            className="w-[min(560px,96vw)] rounded-2xl border border-border bg-card shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div>
                <p className="text-base font-semibold text-foreground">
                  {editingProjectId ? "Editar projeto" : "Cadastrar projeto"}
                </p>
                <p className="text-xs text-muted-foreground">
                  {selectedWorkspace?.name ? `Workspace: ${selectedWorkspace.name}` : "Selecione um workspace."}
                </p>
              </div>
              <button
                type="button"
                onClick={closeCreateProject}
                disabled={isCreatingProject}
                className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-60"
                aria-label="Fechar"
              >
                <X className="size-4" />
              </button>
            </div>

            <form onSubmit={handleCreateProject} className="space-y-3 px-5 py-4">
              <div>
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-foreground">
                  Nome do projeto
                </label>
                <input
                  type="text"
                  value={projectName}
                  onChange={(event) => setProjectName(event.target.value)}
                  placeholder="Ex: Comparativo Abril 2026"
                  className="h-9 w-full rounded-xl border border-input bg-background/70 px-3 text-sm text-foreground placeholder:text-muted-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20"
                  minLength={2}
                  required
                />
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-foreground">
                    Grupo Econômico
                  </label>
                  <Select
                    value={projectConglomerateId}
                    onValueChange={(value) => setProjectConglomerateId(value)}
                    required
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {availableConglomerates.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-foreground">
                    Sistema
                  </label>
                  <Select
                    value={projectCompetitorId}
                    onValueChange={(value) => setProjectCompetitorId(value)}
                    required
                  >
                    <SelectTrigger className="w-full">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {availableCompetitors.map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              <div className="grid gap-3 sm:grid-cols-2">
                <div>
                  <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-foreground">
                    Data inicial
                  </label>
                  <input
                    type="date"
                    value={projectStartDate}
                    onChange={(event) => setProjectStartDate(event.target.value)}
                    className="h-9 w-full rounded-xl border border-input bg-background/70 px-3 text-sm text-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20"
                    required
                  />
                </div>

                <div>
                  <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-foreground">
                    Data final
                  </label>
                  <input
                    type="date"
                    value={projectEndDate}
                    onChange={(event) => setProjectEndDate(event.target.value)}
                    className="h-9 w-full rounded-xl border border-input bg-background/70 px-3 text-sm text-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20"
                    required
                  />
                </div>
              </div>

              <div>
                <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wider text-foreground">
                  Descrição (opcional)
                </label>
                <textarea
                  value={projectDescription}
                  onChange={(event) => setProjectDescription(event.target.value)}
                  rows={3}
                  maxLength={1000}
                  placeholder="Detalhes do objetivo do projeto."
                  className="w-full rounded-xl border border-input bg-background/70 px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20"
                />
              </div>

              {isLoadingProjectDependencies ? (
                <p className="text-xs text-muted-foreground">Carregando grupos econômicos e sistemas...</p>
              ) : null}

              {!isLoadingProjectDependencies && availableConglomerates.length === 0 ? (
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-100">
                  Cadastre ao menos um grupo econômico antes de criar projeto.
                </div>
              ) : null}

              {!isLoadingProjectDependencies && availableCompetitors.length === 0 ? (
                <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-3 py-1.5 text-xs text-amber-100">
                  Cadastre ao menos um sistema antes de criar projeto.
                </div>
              ) : null}

              {createProjectError ? (
                <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-1.5 text-xs text-red-200">
                  {createProjectError}
                </div>
              ) : null}

              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closeCreateProject}
                  disabled={isCreatingProject}
                  className="inline-flex h-8 items-center justify-center rounded-xl border border-border bg-card px-4 text-xs font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={
                    isCreatingProject ||
                    isLoadingProjectDependencies ||
                    !canCreateProject ||
                    availableConglomerates.length === 0 ||
                    availableCompetitors.length === 0
                  }
                  className="inline-flex h-8 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-xs font-bold text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isCreatingProject ? <MorphLoader className="size-3" /> : <Plus className="size-3" />}
                  {editingProjectId ? "Salvar" : "Cadastrar"}
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </aside>
  )
}
