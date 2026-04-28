﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿﻿"use client"

import {
  Bell,
  Boxes,
  Building2,
  Check,
  ChevronDown,
  ChevronRight,
  Edit2,
  HelpCircle,
  LogOut,
  PanelLeft,
  Plus,
  Settings,
  UserRound,
  X,
} from "lucide-react"
import Link from "next/link"
import { AIPanelToggle } from "@/components/agent/ai-panel-toggle"
import { cn } from "@/lib/utils"
import { roleLabel, roleTextClass } from "@/components/dashboard/role-badge"
import { getHeaderMetaFromPathname } from "@/lib/dashboard-navigation"
import { hasOrgPermission } from "@/lib/permissions"
import { logout } from "@/lib/auth"
import { useDashboard } from "@/lib/context/dashboard-context"
import { useToast } from "@/lib/context/toast-context"
import { useDashboardHeader } from "@/lib/context/header-context"
import { useState, useRef, useEffect } from "react"
import { usePathname, useRouter } from "next/navigation"
import { MorphLoader } from "@/components/ui/morph-loader"
import { Tooltip } from "@/components/ui/tooltip"
import { ShiftWordmark } from "@/components/ui/shift-mark"


interface HeaderProps {
  sidebarVisible: boolean
  setSidebarVisible: (visible: boolean) => void
}


function TenantSwitcherTrigger({
  icon: Icon,
  label,
  role,
  placeholder,
  isOpen,
  onClick,
  ariaLabel,
}: {
  icon: React.ComponentType<{ className?: string }>
  label?: string | null
  role?: string | null
  placeholder: string
  isOpen: boolean
  onClick: () => void
  ariaLabel: string
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-2 rounded-md text-left transition-colors hover:bg-accent/50",
        "min-w-[184px] px-3 py-1.5",
        isOpen && "bg-accent/50"
      )}
      aria-label={ariaLabel}
    >
      <Icon className="size-4 shrink-0 text-muted-foreground" />
      <div className="min-w-0 flex-1 leading-tight">
        <p className="truncate text-[13px] font-medium text-foreground">
          {label ?? placeholder}
        </p>
        <p className={cn("truncate text-[11px] font-medium", role ? roleTextClass(role) : "text-muted-foreground")}>
          {role ? roleLabel(role) : placeholder}
        </p>
      </div>
      <ChevronDown className="size-4 shrink-0 text-muted-foreground" />
    </button>
  )
}

function TenantSwitcherItem({
  label,
  role,
  selected,
  onSelect,
  trailing,
}: {
  label: string
  role?: string | null
  selected: boolean
  onSelect: () => void
  trailing?: React.ReactNode
}) {
  return (
    <div className="group flex items-center gap-1 rounded-md hover:bg-accent">
      <button
        type="button"
        onClick={onSelect}
        className="flex min-w-0 flex-1 items-center justify-between px-2 py-2 text-left"
      >
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">
            {label}
          </p>
          <p className={cn("truncate text-xs font-medium", role ? roleTextClass(role) : "text-muted-foreground")}>
            {role ? roleLabel(role) : "Sem papel"}
          </p>
        </div>
        {selected ? <Check className="size-4 shrink-0 text-primary" /> : null}
      </button>
      {trailing}
    </div>
  )
}

export function Header({ sidebarVisible, setSidebarVisible }: HeaderProps) {
  const router = useRouter()
  const pathname = usePathname()
  const { config } = useDashboardHeader()
  const toast = useToast()
  const orgMenuRef = useRef<HTMLDivElement | null>(null)
  const workspaceMenuRef = useRef<HTMLDivElement | null>(null)
  const userMenuRef = useRef<HTMLDivElement | null>(null)
  const [orgMenuOpen, setOrgMenuOpen] = useState(false)
  const [workspaceMenuOpen, setWorkspaceMenuOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const [createOrgOpen, setCreateOrgOpen] = useState(false)
  const [orgName, setOrgName] = useState("")
  const [isCreatingOrg, setIsCreatingOrg] = useState(false)
  const [createWorkspaceOpen, setCreateWorkspaceOpen] = useState(false)
  const [workspaceName, setWorkspaceName] = useState("")
  const [isCreatingWorkspace, setIsCreatingWorkspace] = useState(false)

  const {
    selectedOrganization,
    selectedWorkspace,
    organizations,
    availableWorkspaces,
    setSelectedOrgId,
    setSelectedWorkspaceId,
    createOrganizationAndSelect,
    createWorkspaceAndSelect,
  } = useDashboard()
  const headerMeta = getHeaderMetaFromPathname(pathname)

  useEffect(() => {
    const onDocumentClick = (event: MouseEvent) => {
      const target = event.target as Node
      if (orgMenuRef.current && !orgMenuRef.current.contains(target)) {
        setOrgMenuOpen(false)
      }
      if (workspaceMenuRef.current && !workspaceMenuRef.current.contains(target)) {
        setWorkspaceMenuOpen(false)
      }
      if (userMenuRef.current && !userMenuRef.current.contains(target)) {
        setUserMenuOpen(false)
      }
    }

    document.addEventListener("mousedown", onDocumentClick)
    return () => document.removeEventListener("mousedown", onDocumentClick)
  }, [])

  useEffect(() => {
    if (!createOrgOpen) return
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isCreatingOrg) {
        setCreateOrgOpen(false)
      }
    }
    document.addEventListener("keydown", onEscape)
    return () => document.removeEventListener("keydown", onEscape)
  }, [createOrgOpen, isCreatingOrg])

  useEffect(() => {
    if (!createOrgOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [createOrgOpen])

  useEffect(() => {
    if (!createWorkspaceOpen) return
    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !isCreatingWorkspace) {
        setCreateWorkspaceOpen(false)
      }
    }
    document.addEventListener("keydown", onEscape)
    return () => document.removeEventListener("keydown", onEscape)
  }, [createWorkspaceOpen, isCreatingWorkspace])

  useEffect(() => {
    if (!createWorkspaceOpen) return
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = "hidden"
    return () => {
      document.body.style.overflow = previousOverflow
    }
  }, [createWorkspaceOpen])


  const handleLogout = async () => {
    setUserMenuOpen(false)
    await logout()
    router.replace("/login")
  }

  const openCreateOrg = () => {
    setOrgMenuOpen(false)
    setCreateOrgOpen(true)
  }

  const closeCreateOrg = () => {
    if (isCreatingOrg) return
    setCreateOrgOpen(false)
  }

  const openCreateWorkspace = () => {
    setWorkspaceMenuOpen(false)
    setCreateWorkspaceOpen(true)
  }

  const closeCreateWorkspace = () => {
    if (isCreatingWorkspace) return
    setCreateWorkspaceOpen(false)
  }

  const canCreateOrg = orgName.trim().length >= 2

  const handleCreateOrganization = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!canCreateOrg) return

    setIsCreatingOrg(true)
    try {
      await createOrganizationAndSelect({ name: orgName.trim() })
      setOrgName("")
      setCreateOrgOpen(false)
      toast.success("Organização criada", `"${orgName.trim()}" foi cadastrada com sucesso.`)
    } catch (err) {
      toast.error("Erro ao criar organização", err instanceof Error ? err.message : "Falha ao cadastrar organização.")
    } finally {
      setIsCreatingOrg(false)
    }
  }

  const canCreateWorkspace = workspaceName.trim().length >= 2 && !!selectedOrganization?.id

  const handleCreateWorkspace = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!selectedOrganization?.id) {
      toast.warning("Atenção", "Selecione uma organização primeiro.")
      return
    }
    if (!canCreateWorkspace) return

    setIsCreatingWorkspace(true)
    try {
      await createWorkspaceAndSelect({
        organization_id: selectedOrganization.id,
        name: workspaceName.trim(),
        erp_id: null,
      })
      setWorkspaceName("")
      setCreateWorkspaceOpen(false)
      toast.success("Workspace criado", `"${workspaceName.trim()}" foi cadastrado com sucesso.`)
    } catch (err) {
      toast.error("Erro ao criar workspace", err instanceof Error ? err.message : "Falha ao cadastrar workspace.")
    } finally {
      setIsCreatingWorkspace(false)
    }
  }

  return (
    <>
      <header className="flex h-14 items-center justify-between border-b border-border bg-background px-3 sm:px-4">
        <div className="flex items-center gap-2.5">
          <button
            type="button"
            onClick={() => setSidebarVisible(!sidebarVisible)}
            className="inline-flex size-9 items-center justify-center rounded-md border border-border bg-background text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label={sidebarVisible ? "Esconder sidebar" : "Mostrar sidebar"}
          >
            <PanelLeft className="size-4" />
          </button>

          {!sidebarVisible ? (
            <Link
              href="/home"
              className="inline-flex items-center rounded-md border-r border-border pr-6"
            >
              <span className="block dark:hidden">
                <ShiftWordmark scale={0.32} variant="light" />
              </span>
              <span className="hidden dark:block">
                <ShiftWordmark scale={0.32} variant="dark" />
              </span>
            </Link>
          ) : null}

          <nav
            className={cn(
              "flex items-center gap-1.5 text-[13px]",
              !sidebarVisible && "pl-3"
            )}
          >
            <span className="text-muted-foreground">{headerMeta.groupTitle}</span>
            <ChevronRight className="size-4 text-muted-foreground/50" />
            <span className="font-semibold text-foreground">{headerMeta.pageTitle}</span>
            {config.breadcrumb ? (
              <>
                <ChevronRight className="size-4 text-muted-foreground/50" />
                {config.breadcrumb}
              </>
            ) : null}
          </nav>
        </div>

        <div className="flex items-center gap-2">
          {config.actions?.length ? (
            <div className="flex items-center gap-1">
              {config.actions.map((action) => {
                const Icon = action.icon
                return (
                  <Tooltip key={action.key} text={action.label}>
                    <button
                      type="button"
                      onClick={action.onClick}
                      disabled={action.disabled}
                      className="inline-flex size-9 items-center justify-center rounded-md border border-border bg-background text-muted-foreground transition-colors hover:bg-accent hover:text-foreground disabled:pointer-events-none disabled:opacity-60"
                      aria-label={action.label}
                    >
                      <Icon className="size-4" />
                    </button>
                  </Tooltip>
                )
              })}
            </div>
          ) : null}
          <div ref={orgMenuRef} className="relative">
            <Tooltip text="Selecione a Organização" open={orgMenuOpen}>
              <TenantSwitcherTrigger
                icon={Building2}
                label={selectedOrganization?.name}
                role={selectedOrganization?.role}
                placeholder="Sem organizacao"
                isOpen={orgMenuOpen}
                onClick={() => setOrgMenuOpen((current) => !current)}
                ariaLabel="Selecione a Organização"
              />
            </Tooltip>

            {orgMenuOpen ? (
              <div className="absolute right-0 top-11 z-20 w-72 rounded-xl border border-border bg-card p-2 shadow-lg">
                <p className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Minhas organizacoes
                </p>
                {organizations.map((organization) => (
                  <TenantSwitcherItem
                    key={organization.id}
                    label={organization.name}
                    role={organization.role}
                    selected={selectedOrganization?.id === organization.id}
                    onSelect={() => {
                      setSelectedOrgId(organization.id)
                      setOrgMenuOpen(false)
                    }}
                  />
                ))}
                <div className="mt-1 border-t border-border pt-1">
                  <button
                    type="button"
                    onClick={openCreateOrg}
                    className="inline-flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-primary hover:bg-accent"
                  >
                    <Plus className="size-4" />
                    Criar nova organizacao
                  </button>
                </div>
              </div>
            ) : null}
          </div>

          <div ref={workspaceMenuRef} className="relative">
            <Tooltip text="Selecione o Espaço de Trabalho" open={workspaceMenuOpen}>
              <TenantSwitcherTrigger
                icon={Boxes}
                label={selectedWorkspace?.name}
                role={selectedWorkspace?.my_role}
                placeholder="Sem workspace"
                isOpen={workspaceMenuOpen}
                onClick={() => setWorkspaceMenuOpen((current) => !current)}
                ariaLabel="Selecione o Espaço de Trabalho"
              />
            </Tooltip>

            {workspaceMenuOpen ? (
              <div className="absolute right-0 top-11 z-20 w-72 rounded-xl border border-border bg-card p-2 shadow-lg">
                <p className="px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
                  Workspaces
                </p>
                {availableWorkspaces.map((workspace) => (
                  <TenantSwitcherItem
                    key={workspace.id}
                    label={workspace.name}
                    role={workspace.my_role}
                    selected={selectedWorkspace?.id === workspace.id}
                    onSelect={() => {
                        setSelectedWorkspaceId(workspace.id)
                        setWorkspaceMenuOpen(false)
                    }}
                    trailing={
                      hasOrgPermission(selectedOrganization?.role, "MANAGER") ? (
                      <button
                        type="button"
                        onClick={() => {
                          router.push(`/workspaces/${workspace.id}`)
                          setWorkspaceMenuOpen(false)
                        }}
                        className="mr-1 inline-flex size-7 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
                        title={`Editar workspace ${workspace.name}`}
                        aria-label={`Editar workspace ${workspace.name}`}
                      >
                        <Edit2 className="size-3.5" />
                      </button>
                      ) : undefined
                    }
                  />
                ))}
                {hasOrgPermission(selectedOrganization?.role, "MANAGER") && (
                <div className="mt-1 border-t border-border pt-1">
                  <button
                    type="button"
                    onClick={openCreateWorkspace}
                    disabled={!selectedOrganization}
                    className="inline-flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-primary hover:bg-accent"
                  >
                    <Plus className="size-4" />
                    Criar novo workspace
                  </button>
                </div>
                )}
              </div>
            ) : null}
          </div>

          <Link
            href="/ajuda"
            className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Ajuda"
            title="Ajuda"
          >
            <HelpCircle className="size-4" />
          </Link>

          <button
            type="button"
            className="inline-flex size-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Notificacoes"
          >
            <Bell className="size-4" />
          </button>

          {/* Agente de IA temporariamente oculto. Para reativar, descomente: */}
          {/* <AIPanelToggle /> */}

          <div ref={userMenuRef} className="relative">
            <button
              type="button"
              onClick={() => setUserMenuOpen((current) => !current)}
              className="inline-flex size-9 items-center justify-center rounded-full bg-foreground/10 text-xs font-bold text-foreground hover:bg-foreground/20"
              aria-label="Usuario"
            >
              U
            </button>

            {userMenuOpen ? (
              <div className="absolute right-0 top-11 z-20 w-52 rounded-xl border border-border bg-card p-1.5 shadow-lg">
                <button
                  type="button"
                  onClick={() => setUserMenuOpen(false)}
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm hover:bg-accent"
                >
                  <UserRound className="size-4 text-muted-foreground" />
                  Perfil
                </button>
                <Link
                  href="/configuracoes"
                  onClick={() => setUserMenuOpen(false)}
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm hover:bg-accent"
                >
                  <Settings className="size-4 text-muted-foreground" />
                  Configurações
                </Link>
                <div className="my-1 border-t border-border" />
                <button
                  type="button"
                  onClick={handleLogout}
                  className="flex w-full items-center gap-2 rounded-md px-2.5 py-2 text-left text-sm text-destructive hover:bg-destructive/10"
                >
                  <LogOut className="size-4" />
                  Sair do sistema
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      {createOrgOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
          role="presentation"
          onClick={closeCreateOrg}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Cadastrar organizacao"
            className="w-[min(520px,96vw)] rounded-2xl border border-border bg-card shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div>
                <p className="text-base font-semibold text-foreground">Cadastrar organizacao</p>
                <p className="text-xs text-muted-foreground">Crie uma nova organizacao para usar no sistema.</p>
              </div>
              <button
                type="button"
                onClick={closeCreateOrg}
                disabled={isCreatingOrg}
                className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-60"
                aria-label="Fechar"
              >
                <X className="size-4" />
              </button>
            </div>

            <form onSubmit={handleCreateOrganization} className="px-5 py-4 space-y-3">
              <div>
                <label className="mb-1 block text-[10px] font-semibold text-foreground uppercase tracking-wider">
                  Nome da organizacao
                </label>
                <input
                  type="text"
                  value={orgName}
                  onChange={(event) => setOrgName(event.target.value)}
                  placeholder="Ex: Minha Empresa"
                  className="h-9 w-full rounded-xl border border-input bg-background/70 px-3 text-sm text-foreground placeholder:text-muted-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20"
                  minLength={2}
                  required
                />
              </div>


              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closeCreateOrg}
                  disabled={isCreatingOrg}
                  className="inline-flex h-8 items-center justify-center rounded-xl border border-border bg-card px-4 text-xs font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={isCreatingOrg || !canCreateOrg}
                  className="inline-flex h-8 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-xs font-bold text-primary-foreground transition hover:opacity-90 shadow-[0_0_15px_rgba(255,255,255,0.1)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isCreatingOrg ? <MorphLoader className="size-3" /> : <Plus className="size-3" />}
                  Cadastrar
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}

      {createWorkspaceOpen ? (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4 backdrop-blur-[2px]"
          role="presentation"
          onClick={closeCreateWorkspace}
        >
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Cadastrar workspace"
            className="w-[min(520px,96vw)] rounded-2xl border border-border bg-card shadow-2xl"
            onClick={(event) => event.stopPropagation()}
          >
            <div className="flex items-center justify-between border-b border-border px-5 py-4">
              <div>
                <p className="text-base font-semibold text-foreground">Cadastrar workspace</p>
                <p className="text-xs text-muted-foreground">
                  {selectedOrganization?.name ? `Organizacao: ${selectedOrganization.name}` : "Selecione uma organizacao."}
                </p>
              </div>
              <button
                type="button"
                onClick={closeCreateWorkspace}
                disabled={isCreatingWorkspace}
                className="inline-flex size-8 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground disabled:opacity-60"
                aria-label="Fechar"
              >
                <X className="size-4" />
              </button>
            </div>

            <form onSubmit={handleCreateWorkspace} className="px-5 py-4 space-y-3">
              <div>
                <label className="mb-1 block text-[10px] font-semibold text-foreground uppercase tracking-wider">
                  Nome do workspace
                </label>
                <input
                  type="text"
                  value={workspaceName}
                  onChange={(event) => setWorkspaceName(event.target.value)}
                  placeholder="Ex: Construshow"
                  className="h-9 w-full rounded-xl border border-input bg-background/70 px-3 text-sm text-foreground placeholder:text-muted-foreground outline-none transition focus:border-ring focus:ring-2 focus:ring-ring/20"
                  minLength={2}
                  required
                />
              </div>



              <div className="flex justify-end gap-2 pt-1">
                <button
                  type="button"
                  onClick={closeCreateWorkspace}
                  disabled={isCreatingWorkspace}
                  className="inline-flex h-8 items-center justify-center rounded-xl border border-border bg-card px-4 text-xs font-medium text-foreground transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-60"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={isCreatingWorkspace || !canCreateWorkspace}
                  className="inline-flex h-8 items-center justify-center gap-2 rounded-xl bg-primary px-4 text-xs font-bold text-primary-foreground transition hover:opacity-90 shadow-[0_0_15px_rgba(255,255,255,0.1)] disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {isCreatingWorkspace ? <MorphLoader className="size-3" /> : <Plus className="size-3" />}
                  Cadastrar
                </button>
              </div>
            </form>
          </div>
        </div>
      ) : null}
    </>
  )
}
